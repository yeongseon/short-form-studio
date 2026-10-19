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
import os
from importlib import import_module
from typing import Any
from pathlib import Path
from datetime import datetime, timezone

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

_RUN_LEVEL_TASK_TYPES = frozenset({
    "generate_script",
    "generate_visual_plan",
    "generate_audio",
    "generate_subtitles",
    "render_video",
})
_BROKER_EPOCH_STATE_PATH = Path(
    os.getenv(
        "BROKER_EPOCH_STATE_PATH",
        "/var/lib/short-form-studio/dlq/observed-broker-epoch",
    )
)


async def _rollback_run(run_id: int, celery_task_id: str) -> None:
    """Roll back a run to FAILED state when its stale pending task cannot be recovered.

    Uses conditional_update_run to avoid clobbering a run that the user
    has already retried or that has advanced past the stuck stage.
    Re-raises on failure so DispatchReconciler can record the error.
    """
    from importlib import import_module

    run_service = import_module("creator_service.run_service").run_service
    tracking = import_module("creator_service.task_tracking_service").task_tracking_service
    ok, row = await tracking.rollback_run_if_task_owner(
        celery_task_id,
        run_service.storage,
        run_id,
        _RUN_LEVEL_TASK_TYPES,
        _NON_TERMINAL_GENERATING_STAGES,
        frozenset({"failed", "cancelled", "completed"}),
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
    from creator_service.broker_recovery import (
        BrokerSnapshot,
        oldest_active_wait_seconds,
        recover_broker_snapshot,
        routed_queue_names,
    )

    recovery_summary = {
        "failed": 0,
        "deferred": False,
        "queue_length": 0,
        "oldest_wait_seconds": None,
        "recovery_failures": 0,
    }
    try:
        from celery_app import ensure_broker_epoch, redis, redis_url

        epoch = ensure_broker_epoch()
        client = redis.Redis.from_url(redis_url)
        queue_names = routed_queue_names(
            default_queue=celery_app.conf.task_default_queue,
            routes=celery_app.conf.task_routes,
        )
        queue_length = sum(int(client.llen(queue)) for queue in queue_names)
        ping = celery_app.control.inspect(timeout=2).ping() or {}
        candidates = await task_tracking_service.list_broker_recovery_tasks()
        active_generations = frozenset(
            task.broker_generation
            for task in candidates
            if task.broker_generation is not None
        )
        now = datetime.now(timezone.utc)
        oldest_wait_seconds = oldest_active_wait_seconds(candidates, now=now)
        confirmed_epoch = ensure_broker_epoch()
        snapshot = BrokerSnapshot(
            epoch=epoch.epoch,
            started_at=epoch.started_at,
            queue_length=queue_length,
            oldest_wait_seconds=oldest_wait_seconds,
            workers_online=len(ping),
            confirmed_epoch=confirmed_epoch.epoch,
            active_generations=active_generations,
        )
        fallback_epoch = (
            _BROKER_EPOCH_STATE_PATH.read_text(encoding="utf-8").strip()
            if _BROKER_EPOCH_STATE_PATH.exists()
            else None
        )
        recovered, persisted = await recover_broker_snapshot(
            fallback_epoch=fallback_epoch,
            snapshot=snapshot,
            tracking=task_tracking_service,
            usage=import_module("creator_service.usage_service").usage_service,
            rollback=_rollback_run,
        )
        recovery_summary = {
            "failed": recovered.failed,
            "deferred": recovered.deferred,
            "queue_length": recovered.queue_length,
            "oldest_wait_seconds": recovered.oldest_wait_seconds,
            "recovery_failures": recovered.recovery_failures,
        }
        if persisted:
            _BROKER_EPOCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _BROKER_EPOCH_STATE_PATH.write_text(epoch.epoch, encoding="utf-8")
    except Exception:  # noqa: BLE001 - top-level recovery boundary must fail closed
        logger.warning(
            "Broker recovery evidence unavailable; active work left unchanged",
            extra={"recovery_failures": 1},
            exc_info=True,
        )

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
        "broker_recovery": recovery_summary,
    }
    if result.reenqueued or result.rolled_back or result.stuck_failed or result.errors:
        logger.info("Reconciler pass complete: %s", summary)
    return summary


@celery_app.task(name="reconcile_stale_dispatches", ignore_result=True)
def reconcile_stale_dispatches() -> dict[str, Any]:
    """Celery task: reconcile stale pending dispatches."""
    return run_in_worker_loop(_reconcile_once())
