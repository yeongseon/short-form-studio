# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""Minimal Celery app configuration with structured JSON logging."""

import logging
import os

from celery import Celery
from celery.signals import after_setup_logger
from creator_service.logging_config import setup_json_logging
from creator_service.production_checks import validate_production_config

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
