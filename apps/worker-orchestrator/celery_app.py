# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportMissingImports=false
"""Minimal Celery app configuration with structured JSON logging and DLQ hardening.

Key operational features:
- task_acks_late: Acknowledges messages AFTER execution, enabling redelivery on worker crash
- task_reject_on_worker_lost: Rejects tasks if worker connection is lost (prevents message loss)
- worker_cancel_long_running_tasks_on_connection_loss: Cancels hung tasks on disconnect
- DLQ monitoring: Terminal task failures are stored in Redis list `dlq:creator`

See DLQ_MONITORING.md for operational procedures, alerting setup, and task recovery.
"""

import logging
import os
import json
import signal
from datetime import datetime, timezone
import resource
from typing import Any

from celery import Celery
from celery.signals import after_setup_logger, task_failure, worker_process_init
from importlib import import_module
from creator_service.logging_config import setup_json_logging
from kombu import Exchange, Queue

redis: Any
try:
    import redis
except ImportError:
    redis = None
from creator_service.production_checks import validate_production_config


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    if parsed <= 0:
        return default
    return parsed


MAX_MEMORY_MB = _parse_int_env("MAX_MEMORY_MB", 1024)
_SHUTDOWN_REQUESTED = False
_previous_sigterm_handler: object | None = None
_previous_sigint_handler: object | None = None


def _handle_sigterm(_signum: int, _frame: object | None) -> None:
    global _SHUTDOWN_REQUESTED
    if _SHUTDOWN_REQUESTED:
        return
    _SHUTDOWN_REQUESTED = True
    logging.getLogger(__name__).info("SIGTERM received; beginning Celery graceful shutdown")
    # Chain to previous handler
    prev = _previous_sigterm_handler
    if callable(prev):
        prev(_signum, _frame)


def _handle_sigint(_signum: int, _frame: object | None) -> None:
    global _SHUTDOWN_REQUESTED
    if _SHUTDOWN_REQUESTED:
        return
    _SHUTDOWN_REQUESTED = True
    logging.getLogger(__name__).info("SIGINT received; beginning Celery graceful shutdown")
    # Chain to previous handler
    prev = _previous_sigint_handler
    if callable(prev):
        prev(_signum, _frame)


def is_shutting_down() -> bool:
    """Check if a graceful shutdown has been requested."""
    return _SHUTDOWN_REQUESTED

def _apply_resource_limits() -> None:
    memory_limit_bytes = MAX_MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))


_apply_resource_limits()

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
dlq_max_size = max(1, int(os.getenv("DLQ_MAX_SIZE", "10000")))
dlq_fallback_path = os.getenv("DLQ_FALLBACK_PATH", "/tmp/dlq_fallback.jsonl")

celery_app = Celery(
    "worker-orchestrator",
    broker=redis_url,
    backend=redis_url,
    include=[
        "tasks.generate_script",
        "tasks.generate_visual_plan",
        "tasks.generate_scene_image",
        "tasks.generate_audio",
        "tasks.generate_subtitles",
        "tasks.render_video",
        "tasks.generate_paragraph_audio",
        "tasks.generate_paragraph_subtitles",
    ],
)
celery_app.conf.task_default_queue = "creator"
celery_app.conf.task_queues = (
    Queue(
        "creator",
        Exchange("creator", type="direct"),
        routing_key="creator",
    ),
)
# DLQ Configuration: Controls message acknowledgment and failure handling
# - task_acks_late=True ensures at-least-once delivery by acknowledging AFTER execution
# - task_reject_on_worker_lost=True prevents message loss if worker dies
# This ensures failed tasks are not lost and can be replayed from the DLQ.
celery_app.conf.update(
    # Prefetch only 1 task per worker to prevent queue saturation
    worker_prefetch_multiplier=1,
    # Acknowledge messages AFTER successful execution (enables redelivery on crash)
    task_acks_late=True,
    # Reject tasks if worker connection is lost (returns to queue, not to DLQ)
    task_reject_on_worker_lost=True,
    # Cancel long-running tasks if worker disconnects
    worker_cancel_long_running_tasks_on_connection_loss=True,
)

validate_production_config(service_kind="worker")
try:
    _previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _handle_sigterm)
    _previous_sigint_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _handle_sigint)
except ValueError:
    logging.getLogger(__name__).debug("Skipping signal handler registration: not in main thread")


@after_setup_logger.connect
def setup_celery_logger(_logger: logging.Logger, **_kwargs: object) -> None:
    """Configure Celery logger with JSON formatting."""
    setup_json_logging(service_name="worker", level="INFO")


@worker_process_init.connect
def setup_worker_process_telemetry(**kwargs: object) -> None:
    """
    Configure OpenTelemetry once per worker process.

    Called automatically when a Celery worker process is initialized.
    Safe across forked workers: each worker process calls init_telemetry
    independently. The idempotency guard in init_telemetry() ensures that
    multiple calls within the same process are no-ops.
    """
    _ = kwargs
    telemetry_module = import_module("telemetry")
    telemetry_module.init_telemetry(service_name="worker")


def _record_failed_task_to_dlq(
    task_id: str | None,
    task_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exception: BaseException,
) -> None:
    payload = {
        "task_id": task_id,
        "task_name": task_name,
        "args": args,
        "kwargs": kwargs,
        "exception": repr(exception),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    def _write_dlq_fallback(entry: dict[str, Any], error: BaseException | None = None) -> None:
        logger = logging.getLogger(__name__)
        try:
            with open(dlq_fallback_path, "a", encoding="utf-8") as fallback_file:
                fallback_file.write(json.dumps(entry, default=str))
                fallback_file.write("\n")
            logger.warning(
                "DLQ Redis write failed; wrote entry to fallback file",
                extra={"dlq_fallback_path": dlq_fallback_path},
            )
        except Exception as fallback_error:
            logger.error(
                "DLQ Redis write failed and fallback file write also failed",
                extra={"dlq_fallback_path": dlq_fallback_path},
                exc_info=(type(fallback_error), fallback_error, fallback_error.__traceback__),
            )
        if error is not None:
            logger.error(
                "DLQ Redis write failure",
                exc_info=(type(error), error, error.__traceback__),
            )

    if redis is None:
        _write_dlq_fallback(payload)
        return

    try:
        client = redis.Redis.from_url(redis_url)
        client.lpush("dlq:creator", json.dumps(payload, default=str))
        client.ltrim("dlq:creator", 0, dlq_max_size - 1)
    except Exception as redis_error:
        _write_dlq_fallback(payload, redis_error)


def _should_record_to_dlq(sender: Any, exception: BaseException | None = None) -> bool:
    from creator_provider.exceptions import ProviderTimeoutError, RateLimitError

    if not isinstance(exception, (ProviderTimeoutError, RateLimitError)):
        return True

    request = getattr(sender, "request", None)
    retries = getattr(request, "retries", None)
    max_retries = getattr(sender, "max_retries", None)
    if isinstance(retries, int) and isinstance(max_retries, int):
        return retries >= max_retries
    return True


@task_failure.connect
def handle_task_failure(
    sender: Any = None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    **_: Any,
) -> None:
    if exception is None:
        return
    if not _should_record_to_dlq(sender, exception):
        return

    task_name = getattr(sender, "name", "unknown_task")
    _record_failed_task_to_dlq(
        task_id=task_id,
        task_name=task_name,
        args=args,
        kwargs=kwargs or {},
        exception=exception,
    )
