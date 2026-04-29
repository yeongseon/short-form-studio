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
from datetime import datetime, timezone
from typing import Any

from celery import Celery
from celery.signals import after_setup_logger, task_failure
from creator_service.logging_config import setup_json_logging
from kombu import Exchange, Queue

redis: Any
try:
    import redis
except ImportError:
    redis = None

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
dlq_max_size = max(1, int(os.getenv("DLQ_MAX_SIZE", "10000")))

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


@after_setup_logger.connect
def setup_celery_logger(_logger: logging.Logger, **_kwargs: object) -> None:
    """Configure Celery logger with JSON formatting."""
    setup_json_logging(service_name="worker", level="INFO")


def _record_failed_task_to_dlq(
    task_id: str | None,
    task_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    exception: BaseException,
) -> None:
    if redis is None:
        logging.getLogger(__name__).warning("Redis client not installed; cannot write DLQ entry")
        return

    client = redis.Redis.from_url(redis_url)
    payload = {
        "task_id": task_id,
        "task_name": task_name,
        "args": args,
        "kwargs": kwargs,
        "exception": repr(exception),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    client.lpush("dlq:creator", json.dumps(payload, default=str))
    client.ltrim("dlq:creator", 0, dlq_max_size - 1)


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

    task_name = getattr(sender, "name", "unknown_task")
    _record_failed_task_to_dlq(
        task_id=task_id,
        task_name=task_name,
        args=args,
        kwargs=kwargs or {},
        exception=exception,
    )
