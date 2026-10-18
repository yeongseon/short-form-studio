from __future__ import annotations

from typing import Any


def _terminal_services() -> Any:
    from creator_service.task_tracking_service import task_tracking_service
    from creator_service.usage_service import usage_service

    return task_tracking_service.fail_claimed_and_cancel_quota


def finalize_hard_timeout(
    task_id: str, claim_token: str, run_id: int, timeout: float,
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
            frozenset({"RENDER_GENERATING"}),
        )

    run_in_worker_loop(finalize())
