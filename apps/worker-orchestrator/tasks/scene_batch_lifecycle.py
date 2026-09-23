"""Cooperative scene checkpoints and guarded batch completion."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import anyio
from celery.exceptions import Ignore
from creator_domain.models.stage import RunStage
from creator_service.run_service import RunService
from tasks import task_runner
from tasks.task_runner import TaskContext, TaskResult

logger = logging.getLogger(__name__)

SAFE_SUCCESS_STAGES = frozenset({
    RunStage.VISUAL_PLAN_REVIEW.value,
    RunStage.VISUAL_ASSET_GENERATING.value,
    RunStage.VISUAL_ASSET_REVIEW.value,
})
SAFE_FAILURE_STAGES = frozenset({
    RunStage.VISUAL_PLAN_REVIEW.value,
    RunStage.VISUAL_ASSET_GENERATING.value,
})


@dataclass
class SceneBatch:
    """Accumulate accepted results; cancellation never rolls back accepted media."""

    ctx: TaskContext
    runs: RunService
    results: list[dict[str, object]] = field(default_factory=list)
    failures: list[dict[str, object]] = field(default_factory=list)
    cancelled: bool = False
    local_outputs: set[Path] = field(default_factory=set)

    async def checkpoint(self) -> None:
        task = await task_runner._task_tracking_service.storage.get_by_celery_id(self.ctx.task_id)
        run = await self.runs.storage.get_run(self.ctx.run_id)
        if (
            run is None
            or run.get("status") in task_runner._TERMINAL_STATUSES
            or (task is not None and task.get("status") == "revoked")
        ):
            raise Ignore()

    async def backoff(self, seconds: float) -> None:
        # DB cancellation has no wakeup signal; bounded sleeps avoid busy polling.
        remaining = seconds
        while remaining > 0:
            await self.checkpoint()
            interval = min(remaining, 0.5)
            await anyio.sleep(interval)
            remaining -= interval
        await self.checkpoint()

    async def finish(self, total: int, metadata: dict[str, object]) -> TaskResult:
        status = "failed" if len(self.failures) == total else "partial" if self.failures else "success"
        try:
            await self.checkpoint()
        except Ignore:
            self.cancelled = True
        if not self.cancelled:
            failed = len(self.failures) == total
            applied, row = await self.runs.storage.conditional_update_run(
                self.ctx.run_id,
                {
                    "current_stage": RunStage.FAILED if failed else RunStage.VISUAL_ASSET_REVIEW,
                    "status": "failed" if failed else "running",
                },
                expected_stages=SAFE_FAILURE_STAGES if failed else SAFE_SUCCESS_STAGES,
                rejected_statuses=task_runner._TERMINAL_STATUSES,
            )
            if not applied and row is not None and row.get("status") in task_runner._TERMINAL_STATUSES:
                self.cancelled = True
        if self.cancelled:
            for path in self.local_outputs:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Scene local cleanup failed", extra={"run_id": self.ctx.run_id})
        return TaskResult(
            status="cancelled" if self.cancelled else status,
            extra={
                **metadata,
                "total_scenes": total,
                "succeeded": len(self.results),
                "failed": len(self.failures),
                "scene_results": self.results + self.failures,
            },
        )
