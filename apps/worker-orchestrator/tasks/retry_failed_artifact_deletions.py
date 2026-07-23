"""Periodic task: retry failed artifact deletions.

Scheduled via Celery Beat to run every 5 minutes. Picks up artifacts that
have ``delete_requested_at`` set but couldn't be deleted on the first attempt
(e.g., storage transient failure, process crash between storage delete and
DB row removal).

The underlying logic lives in
``creator_service.artifact_download_service.retry_failed_deletions`` — this
module is a thin Celery wrapper that calls it inside the worker event loop.
"""

from __future__ import annotations

import logging
from typing import Any

from celery_app import celery_app
from worker_loop import run_in_worker_loop

logger = logging.getLogger(__name__)


async def _retry_once() -> dict[str, Any]:
    """Run one retry pass."""
    from creator_service.artifact_download_service import artifact_download_service

    deleted = await artifact_download_service.retry_failed_deletions(max_retries=5)
    if deleted:
        logger.info("retry_failed_deletions: cleaned up %d artifacts", deleted)
    return {"deleted": deleted}


@celery_app.task(name="retry_failed_artifact_deletions", ignore_result=True)
def retry_failed_artifact_deletions() -> dict[str, Any]:
    """Celery task: retry deletion of artifacts that previously failed."""
    return run_in_worker_loop(_retry_once())
