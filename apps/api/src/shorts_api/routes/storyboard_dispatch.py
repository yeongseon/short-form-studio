"""Storyboard dispatch helper — shared dispatch-track-revoke logic."""

from __future__ import annotations

import logging
from typing import Callable

from creator_service.task_tracking_service import task_tracking_service
from creator_service.usage_service import cancel_workspace_quota_reservation
from fastapi import HTTPException

logger = logging.getLogger(__name__)


async def _get_fresh_run_for_dispatch(run_id: int, workspace_id: int):
    """Re-read run to check cancellation status."""
    from creator_service.run_service import run_service

    try:
        return await run_service.get_run(run_id, workspace_id=workspace_id)
    except Exception:
        logger.warning("Failed to re-read run %s for dispatch check", run_id, exc_info=True)
        return None


def _is_cancelled(run) -> bool:
    return run is None or getattr(run, "status", None) == "cancelled"


def _revoke_task(task_id: str) -> None:
    """Best-effort revoke of a Celery task."""
    try:
        celery_app = __import__("celery_app").celery_app
        celery_app.control.revoke(task_id, terminate=True)
    except Exception:
        logger.warning("Failed to revoke task %s", task_id)


async def _revoke_and_mark(task_id: str) -> None:
    """Revoke a Celery task and mark it revoked in tracking."""
    _revoke_task(task_id)
    try:
        await task_tracking_service.mark_tasks_revoked([task_id])
    except Exception:
        logger.warning("Failed to mark task %s as revoked in tracking", task_id)


async def dispatch_storyboard_task_with_tracking(
    *,
    run_id: int,
    workspace_id: int,
    operation_type: str,
    task_type: str,
    dispatch: Callable[[], str],
    error_detail: str = "Failed to enqueue task",
) -> str:
    """Dispatch a storyboard task with full quota/tracking/cancel safety.

    Performs:
    1. Pre-dispatch cancelled check
    2. Dispatch (call the provided callable)
    3. Record task in tracking
    4. Post-dispatch cancelled check (TOCTOU close)

    On any failure: revokes task, cancels quota, raises HTTPException.

    Returns the Celery task_id on success.
    """
    # Pre-dispatch cancel check
    fresh_run = await _get_fresh_run_for_dispatch(run_id, workspace_id)
    if _is_cancelled(fresh_run):
        await cancel_workspace_quota_reservation(workspace_id, operation_type)
        raise HTTPException(status_code=409, detail="Run was cancelled before dispatch")

    # Dispatch
    try:
        task_id = dispatch()
    except Exception:
        await cancel_workspace_quota_reservation(workspace_id, operation_type)
        raise HTTPException(status_code=503, detail=error_detail) from None

    # Track
    try:
        await task_tracking_service.record_task_queued(run_id, task_type, task_id)
    except Exception:
        await _revoke_and_mark(task_id)
        await cancel_workspace_quota_reservation(workspace_id, operation_type)
        raise HTTPException(status_code=503, detail=error_detail) from None

    # Post-dispatch cancel check (TOCTOU window close)
    post_run = await _get_fresh_run_for_dispatch(run_id, workspace_id)
    if _is_cancelled(post_run):
        await _revoke_and_mark(task_id)
        await cancel_workspace_quota_reservation(workspace_id, operation_type)
        raise HTTPException(status_code=409, detail="Run was cancelled during dispatch")

    return task_id


async def dispatch_storyboard_task_bulk(
    *,
    run_id: int,
    workspace_id: int,
    operation_type: str,
    task_type: str,
    section_id: str,
    dispatch: Callable[[], str],
) -> dict[str, str]:
    """Dispatch a single task within a bulk loop. Returns result dict.

    Unlike the single-endpoint version, bulk does NOT raise on individual
    failures — it returns an error dict so the loop can continue.
    Raises HTTPException only on post-dispatch cancellation (hard stop).
    """
    from creator_service.usage_service import check_workspace_quota

    allowed, reason = await check_workspace_quota(workspace_id, operation_type=operation_type)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    fresh_run = await _get_fresh_run_for_dispatch(run_id, workspace_id)
    if _is_cancelled(fresh_run):
        await cancel_workspace_quota_reservation(workspace_id, operation_type)
        return {"section_id": section_id, "task_id": "", "error": "dispatch_failed"}

    try:
        task_id = dispatch()
    except Exception:
        await cancel_workspace_quota_reservation(workspace_id, operation_type)
        logger.exception("Failed to dispatch %s for section %s of run %s", task_type, section_id, run_id)
        return {"section_id": section_id, "task_id": "", "error": "dispatch_failed"}

    try:
        await task_tracking_service.record_task_queued(run_id, task_type, task_id)
    except Exception:
        await _revoke_and_mark(task_id)
        await cancel_workspace_quota_reservation(workspace_id, operation_type)
        logger.exception("Failed to track %s for section %s of run %s", task_type, section_id, run_id)
        return {"section_id": section_id, "task_id": "", "error": "dispatch_failed"}

    post_run = await _get_fresh_run_for_dispatch(run_id, workspace_id)
    if _is_cancelled(post_run):
        await _revoke_and_mark(task_id)
        await cancel_workspace_quota_reservation(workspace_id, operation_type)
        raise HTTPException(status_code=409, detail="Run was cancelled during dispatch")

    return {"section_id": section_id, "task_id": task_id}
