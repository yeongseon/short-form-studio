"""Dispatch reconciler: recovers stale pending and stuck running tasks.

Phase 1 — Stale pending: When a dispatch crashes between recording the
task as 'pending' and enqueueing it to the broker, the task is left in
'pending' state with no Celery message.  The reconciler re-enqueues or
rolls back the associated run.

Phase 2 — Stuck running: Tasks stuck in 'running' state beyond a
configurable threshold (default 900 s, which exceeds the Celery hard
time limit of 660 s) are marked as failed via a CAS guard
(mark_failed_if_running) and their runs are rolled back.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    """Summary of a reconciliation pass."""

    reenqueued: int = 0
    rolled_back: int = 0
    stuck_failed: int = 0
    errors: list[str] = field(default_factory=list)


class DispatchReconciler:
    """Scans for stale 'pending' tasks and recovers them.

    Args:
        task_tracking_service: Service for querying/updating task records.
        enqueue_fn: Async callable(celery_task_id, task_type, run_id) -> bool.
            Returns True if enqueue succeeded, False otherwise.
        rollback_fn: Optional async callable(run_id, celery_task_id) -> None.
            Called when re-enqueue fails to roll back the run stage.
        threshold_seconds: How long a task must be 'pending' before it's
            considered stale (default 120s).
        stuck_threshold_seconds: How long a task can be 'running' before
            it's considered stuck (default 900s = 15 min). Must exceed the
            maximum Celery task time_limit (currently 660s) plus scheduler jitter.
    """

    def __init__(
        self,
        *,
        task_tracking_service: Any,
        enqueue_fn: Callable[..., Awaitable[bool]],
        rollback_fn: Callable[..., Awaitable[None]] | None = None,
        threshold_seconds: int = 120,
        stuck_threshold_seconds: int = 900,
    ) -> None:
        self._tracking = task_tracking_service
        self._enqueue_fn = enqueue_fn
        self._rollback_fn = rollback_fn
        self._threshold_seconds = threshold_seconds
        self._stuck_threshold_seconds = stuck_threshold_seconds
        if stuck_threshold_seconds <= 660:
            raise ValueError(
                f"stuck_threshold_seconds ({stuck_threshold_seconds}) must exceed "
                f"the maximum Celery task time_limit (660s) to avoid "
                f"false-positive stuck detection"
            )

    async def reconcile(self) -> ReconcileResult:
        """Run one reconciliation pass.

        Returns a ReconcileResult summarizing what happened.
        """
        result = ReconcileResult()
        stale_tasks = await self._tracking.find_stale_pending_tasks(self._threshold_seconds)

        for task in stale_tasks:
            celery_task_id = task.celery_task_id
            task_type = task.task_type
            run_id = task.run_id

            try:
                ok = await self._enqueue_fn(celery_task_id, task_type, run_id)
            except Exception as exc:
                logger.warning(
                    "Reconciler: enqueue failed for task %s (run %d): %s",
                    celery_task_id,
                    run_id,
                    exc,
                )
                ok = False

            if ok:
                # Promote to queued
                try:
                    await self._tracking.promote_pending_to_queued(celery_task_id)
                except Exception:
                    logger.warning(
                        "Reconciler: promote failed for %s, task may still be pending",
                        celery_task_id,
                        exc_info=True,
                    )
                result.reenqueued += 1
                logger.info(
                    "Reconciler: re-enqueued stale task %s (run %d)",
                    celery_task_id,
                    run_id,
                )
            else:
                # Roll back the run stage
                if self._rollback_fn is not None:
                    try:
                        await self._rollback_fn(run_id, celery_task_id)
                    except Exception as exc:
                        error_msg = (
                            f"Reconciler: rollback failed for run {run_id} "
                            f"(task {celery_task_id}): {exc}"
                        )
                        logger.error(error_msg)
                        result.errors.append(error_msg)

                # Mark the task as failed so it's not retried again
                try:
                    await self._tracking.mark_failed(
                        celery_task_id,
                        error_code="reconciler_rollback",
                        error_message="Stale pending task could not be re-enqueued",
                    )
                except Exception:
                    logger.warning(
                        "Reconciler: failed to mark task %s as failed",
                        celery_task_id,
                        exc_info=True,
                    )

                result.rolled_back += 1
                logger.info(
                    "Reconciler: rolled back stale task %s (run %d)",
                    celery_task_id,
                    run_id,
                )


        # --- Phase 2: stuck running tasks ---
        stuck_tasks = await self._tracking.find_stuck_tasks(self._stuck_threshold_seconds)

        for task in stuck_tasks:
            celery_task_id = task.celery_task_id
            run_id = task.run_id

            # Mark the task as failed FIRST — this is the CAS guard.
            # Only if the transition succeeds (task was still running)
            # do we roll back the run.  This prevents clobbering a run
            # whose task completed successfully between the scan and now.
            try:
                marked = await self._tracking.mark_failed_if_running(
                    celery_task_id,
                    error_code="stuck_running_timeout",
                    error_message=(
                        f"Task stuck in running state for >{self._stuck_threshold_seconds}s"
                    ),
                )
            except Exception as exc:
                error_msg = (
                    f"Reconciler: failed to mark stuck task {celery_task_id} "
                    f"as failed: {exc}"
                )
                logger.warning(error_msg, exc_info=True)
                result.errors.append(error_msg)
                marked = None

            if marked is not None:
                result.stuck_failed += 1
                logger.info(
                    "Reconciler: marked stuck running task %s (run %d) as failed",
                    celery_task_id,
                    run_id,
                )
                # Roll back the run stage only after confirming the task
                # actually transitioned to failed (CAS succeeded).
                if self._rollback_fn is not None:
                    try:
                        await self._rollback_fn(run_id, celery_task_id)
                    except Exception as exc:
                        error_msg = (
                            f"Reconciler: stuck-task rollback failed for run {run_id} "
                            f"(task {celery_task_id}): {exc}"
                        )
                        logger.error(error_msg)
                        result.errors.append(error_msg)
            else:
                logger.info(
                    "Reconciler: stuck task %s (run %d) already transitioned, skipped",
                    celery_task_id,
                    run_id,
                )

        return result
