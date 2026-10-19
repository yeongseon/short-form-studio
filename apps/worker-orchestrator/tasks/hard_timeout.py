from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from celery import Task
from celery.worker.request import Request


def _terminal_services() -> Any:
    from creator_service.task_tracking_service import task_tracking_service
    from creator_service.usage_service import usage_service

    return task_tracking_service.fail_claimed_and_cancel_quota


def finalize_hard_timeout(
    task_id: str,
    claim_token: str,
    run_id: int,
    timeout: float,
    safe_failure_stages: frozenset[str],
) -> None:
    from worker_loop import run_in_worker_loop

    finalize_claimed = _terminal_services()

    async def finalize() -> None:
        from creator_service.run_service import run_service
        from creator_service.usage_service import usage_service

        await finalize_claimed(
            task_id,
            claim_token,
            usage_service.storage,
            "TIMEOUT",
            f"The task exceeded its {timeout} second hard time limit",
            run_service.storage,
            run_id,
            safe_failure_stages,
        )

    run_in_worker_loop(finalize())


class ProductionRequest(Request):
    def on_timeout(self, soft: bool, timeout: float) -> None:
        super().on_timeout(soft, timeout)
        if soft or not isinstance(self.id, str) or not self.args:
            return
        run_id = self.args[0]
        safe_failure_stages = self.task.hard_timeout_safe_failure_stages
        if (
            isinstance(run_id, int)
            and isinstance(self.worker_pid, int)
            and isinstance(safe_failure_stages, frozenset)
        ):
            finalize_hard_timeout(
                self.id,
                f"{self.id}:{self.worker_pid}",
                run_id,
                timeout,
                safe_failure_stages,
            )
            self.task.hard_timeout_cleanup(run_id, self.id)


class ProductionTask(Task):
    Request = ProductionRequest
    hard_timeout_safe_failure_stages: frozenset[str] = frozenset()
    hard_timeout_cleanup: Callable[[int, str], None] = staticmethod(lambda _run_id, _task_id: None)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.request.claim_token = f"{self.request.id}:{os.getpid()}"
        return super().__call__(*args, **kwargs)


def production_task(
    safe_failure_stages: frozenset[str],
    cleanup: Callable[[int, str], None] | None = None,
) -> type[ProductionTask]:
    class ConfiguredProductionTask(ProductionTask):
        hard_timeout_safe_failure_stages = safe_failure_stages
        hard_timeout_cleanup = staticmethod(cleanup or (lambda _run_id, _task_id: None))

    return ConfiguredProductionTask


def production_time_limits(soft: int, hard: int) -> tuple[int | None, int]:
    override = os.getenv("WORKER_TOPOLOGY_PRODUCTION_HARD_TIME_LIMIT")
    if (
        os.getenv("ENVIRONMENT") == "test"
        and os.getenv("WORKER_TOPOLOGY_PROBE_ENABLED") == "1"
        and override is not None
    ):
        hard = int(override)
        return None, hard
    return soft, hard
