# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""Minimal Celery app configuration with structured JSON logging."""

import logging
import os

from celery import Celery
from celery.signals import after_setup_logger

from creator_service.logging_config import setup_json_logging

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("worker-orchestrator", broker=redis_url, backend=redis_url)
celery_app.conf.task_default_queue = "creator"


@after_setup_logger.connect
def setup_celery_logger(logger: logging.Logger, **kwargs: object) -> None:
    """Configure Celery logger with JSON formatting."""
    setup_json_logging(service_name="worker", level="INFO")
