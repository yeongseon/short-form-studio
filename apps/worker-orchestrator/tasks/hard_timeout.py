from __future__ import annotations

from typing import Any


def _terminal_services() -> tuple[Any, Any, Any, Any]:
    from creator_service.run_service import run_service
    from creator_service.task_tracking_service import task_tracking_service
    from creator_service.usage_service import usage_service

    return (
        task_tracking_service.mark_failed_if_running,
        usage_service.cancel_owned,
        run_service.storage.get_run,
        run_service.storage.conditional_update_run,
    )


def finalize_hard_timeout(task_id: str, run_id: int, timeout: float) -> None:
    from worker_loop import run_in_worker_loop

    mark_failed, cancel_owned, get_run, update_run = _terminal_services()

    async def finalize() -> None:
        outcome = await mark_failed(
            task_id,
            "TIMEOUT",
            f"The task exceeded its {timeout} second hard time limit",
        )
        await cancel_owned(task_id)
        run = await get_run(run_id)
        if run is None:
            return
        stage = run.get("current_stage")
        if not isinstance(stage, str):
            return
        await update_run(
            run_id,
            {"current_stage": "FAILED", "status": "failed"},
            expected_stages=frozenset({stage}),
            rejected_statuses=frozenset({"failed", "cancelled", "completed"}),
        )

    run_in_worker_loop(finalize())
