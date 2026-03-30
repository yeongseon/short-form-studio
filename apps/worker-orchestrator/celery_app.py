# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""Minimal Celery app configuration."""

import os

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery("worker-orchestrator", broker=redis_url, backend=redis_url)
celery_app.conf.task_default_queue = "creator"

# Auto-discover tasks from the tasks package
celery_app.autodiscover_tasks(["tasks"])
