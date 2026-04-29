# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""Minimal Celery app configuration with structured JSON logging."""

import logging
import os
import resource

from celery import Celery
from celery.signals import after_setup_logger
from creator_service.logging_config import setup_json_logging
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


def _apply_resource_limits() -> None:
    memory_limit_bytes = MAX_MEMORY_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))


_apply_resource_limits()


redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

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

validate_production_config(service_kind="worker")


@after_setup_logger.connect
def setup_celery_logger(_logger: logging.Logger, **_kwargs: object) -> None:
    """Configure Celery logger with JSON formatting."""
    setup_json_logging(service_name="worker", level="INFO")
