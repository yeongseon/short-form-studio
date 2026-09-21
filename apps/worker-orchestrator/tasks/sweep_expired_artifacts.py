"""Periodic task: sweep expired artifacts.

Scheduled via Celery Beat to run every 10 minutes. Picks up artifacts whose
``expires_at`` has passed and marks them ``delete_requested_at = NOW()``.
The actual storage + DB row removal is handled by the existing
``retry_failed_artifact_deletions`` task (``FOR UPDATE SKIP LOCKED``).

Splitting sweep (this task) from delete (the retry task) keeps each unit
small, idempotent, and independently retryable.

See migration 031 for the configurable ``ARTIFACT_RETENTION_DAYS`` env var
that drives the ``expires_at`` default.
"""

from __future__ import annotations

import logging
from typing import Any

from celery_app import celery_app
from worker_loop import run_in_worker_loop

logger = logging.getLogger(__name__)


async def _sweep_once() -> dict[str, Any]:
    """Run one sweep pass."""
    from creator_service.artifact_download_service import artifact_download_service

    marked = await artifact_download_service.sweep_expired()
    if marked:
        logger.info("sweep_expired_artifacts: marked %d artifacts for deletion", marked)
    return {"marked": marked}


@celery_app.task(name="sweep_expired_artifacts", ignore_result=True)
def sweep_expired_artifacts() -> dict[str, Any]:
    """Celery task: mark expired artifacts for deletion."""
    return run_in_worker_loop(_sweep_once())
