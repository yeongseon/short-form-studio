# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportMissingImports=false
"""Minimal Celery app configuration with structured JSON logging."""

import logging
import os
from importlib import import_module

from celery import Celery
from celery.signals import after_setup_logger, worker_process_init
from creator_service.logging_config import setup_json_logging

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


@after_setup_logger.connect
def setup_celery_logger(logger: logging.Logger, **kwargs: object) -> None:
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
    telemetry_module = import_module("telemetry")
    telemetry_module.init_telemetry(service_name="worker")
