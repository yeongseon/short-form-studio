"""Periodic task: reconcile stale 'pending' dispatch records.

Scheduled via Celery Beat to run every 60 seconds. Finds tasks stuck
in 'pending' state (DB-first dispatch record created but broker enqueue
never completed) and marks them as failed + sets the run to FAILED.

NOTE: Re-enqueue is not attempted because the original dispatch arguments
(idea_brief, model_key, voice, etc.) are not persisted in the task record.
The user must retry the operation manually. A future improvement could
persist dispatch payloads to enable automatic re-enqueue.
"""
from __future__ import annotations


from worker_loop import run_in_worker_loop
import logging
from typing import Any

from celery_app import celery_app

logger = logging.getLogger(__name__)

# Non-terminal stages eligible for rollback.  The reconciler only sets
# a run to FAILED when the run is still in one of these stages, meaning
# it hasn't progressed past the point where the stale task was supposed
# to execute.  If a user already retried (advancing the run to a new
# stage), the conditional update will be a no-op.
_NON_TERMINAL_GENERATING_STAGES = frozenset({
    # Active generation stages (task is running or about to run)
    "SCRIPT_GENERATING",
    "VISUAL_PLAN_GENERATING",
    "VISUAL_ASSET_GENERATING",
    "AUDIO_GENERATING",
    "SUBTITLE_GENERATING",
    "RENDER_GENERATING",
    # Pre-generation / review stages (dispatch just happened or user hasn't retried)
    "IDEA_READY",
    "VISUAL_PLAN_SETUP",
    "SCRIPT_REVIEW",
    "VISUAL_PLAN_REVIEW",
    "VISUAL_ASSET_REVIEW",
})


async def _rollback_run(run_id: int, celery_task_id: str) -> None:
    """Roll back a run to FAILED state when its stale pending task cannot be recovered.

    Uses conditional_update_run to avoid clobbering a run that the user
    has already retried or that has advanced past the stuck stage.
    Re-raises on failure so DispatchReconciler can record the error.
    """
    from importlib import import_module

    run_service = import_module("creator_service.run_service").run_service
    ok, row = await run_service.storage.conditional_update_run(
        run_id,
        {"current_stage": "FAILED", "status": "failed"},
        expected_stages=_NON_TERMINAL_GENERATING_STAGES,
        rejected_statuses=frozenset({"failed", "cancelled", "completed"}),
    )
    if ok:
        logger.info(
            "Reconciler: rolled back run %d to FAILED (stale task %s)",
            run_id,
            celery_task_id,
        )
    else:
        current_stage = row.get("current_stage") if row else "unknown"
        logger.info(
            "Reconciler: skipped rollback for run %d — already at stage %s "
            "(stale task %s)",
            run_id,
            current_stage,
            celery_task_id,
        )


async def _always_fail_enqueue(celery_task_id: str, task_type: str, run_id: int) -> bool:
    """Always returns False — re-enqueue is not possible without persisted dispatch args."""
    logger.info(
        "Reconciler: cannot re-enqueue task %s (type=%s, run=%d) — "
        "original dispatch arguments not persisted",
        celery_task_id,
        task_type,
        run_id,
    )
    return False


async def _reconcile_once() -> dict[str, Any]:
    """Run one reconciliation pass."""
    from creator_service.dispatch_reconciler import DispatchReconciler
    from creator_service.task_tracking_service import task_tracking_service

    reconciler = DispatchReconciler(
        task_tracking_service=task_tracking_service,
        enqueue_fn=_always_fail_enqueue,
        rollback_fn=_rollback_run,
        threshold_seconds=120,
        stuck_threshold_seconds=900,
    )
    result = await reconciler.reconcile()
    summary = {
        "reenqueued": result.reenqueued,
        "rolled_back": result.rolled_back,
        "stuck_failed": result.stuck_failed,
        "errors": result.errors,
    }
    if result.reenqueued or result.rolled_back or result.stuck_failed or result.errors:
        logger.info("Reconciler pass complete: %s", summary)
    return summary


@celery_app.task(name="reconcile_stale_dispatches", ignore_result=True)
def reconcile_stale_dispatches() -> dict[str, Any]:
    """Celery task: reconcile stale pending dispatches."""
    return run_in_worker_loop(_reconcile_once())
