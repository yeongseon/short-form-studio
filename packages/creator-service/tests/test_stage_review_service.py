import asyncio

import pytest
from creator_service.run_service import InMemoryRunStorage
from creator_service.stage_review_service import InMemoryStageReviewStorage, StageReviewService


def run(coro):
    return asyncio.run(coro)


class _RunServiceStub:
    def __init__(self, storage: InMemoryRunStorage) -> None:
        self.storage = storage

    async def get_run(self, run_id: int, workspace_id: int | None = None):
        return await self.storage.get_run(run_id, workspace_id=workspace_id)


class _FailingReviewStorage(InMemoryStageReviewStorage):
    async def create_review(self, row: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("review insert failed")


def test_approve_and_advance_rolls_back_stage_when_review_insert_fails() -> None:
    run_storage = InMemoryRunStorage()
    run_row = run(
        run_storage.create_run(
            {
                "project_id": 1,
                "workspace_id": 1,
                "current_stage": "SCRIPT_REVIEW",
                "status": "pending",
            }
        )
    )
    run_id = int(run_row["id"])

    storage = _FailingReviewStorage()
    service = StageReviewService(storage)
    run_service = _RunServiceStub(run_storage)

    with pytest.raises(RuntimeError, match="review insert failed"):
        run(
            service.approve_and_advance(
                run_service=run_service,
                run_id=run_id,
                stage_name="SCRIPT_REVIEW",
                target_stage="VISUAL_PLAN_SETUP",
                workspace_id=1,
            )
        )

    latest = run(run_storage.get_run(run_id, workspace_id=1))
    assert latest is not None
    assert latest["current_stage"] == "SCRIPT_REVIEW"


class _FailingReviewAndRollbackStorage(InMemoryStageReviewStorage):
    """Review insert fails, and we rig the run storage so rollback CAS also fails."""

    async def create_review(self, row: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("review insert failed")


def test_approve_raises_inconsistency_when_rollback_also_fails() -> None:
    """If review insert fails AND rollback CAS fails, a RuntimeError with
    'Stage rollback failed' must be raised instead of the original error."""
    run_storage = InMemoryRunStorage()
    run_row = run(
        run_storage.create_run(
            {
                "project_id": 1,
                "workspace_id": 1,
                "current_stage": "SCRIPT_REVIEW",
                "status": "pending",
            }
        )
    )
    run_id = int(run_row["id"])

    storage = _FailingReviewAndRollbackStorage()
    service = StageReviewService(storage)
    run_svc = _RunServiceStub(run_storage)

    # First, do the approve which will:
    # 1. CAS stage from SCRIPT_REVIEW -> VISUAL_PLAN_SETUP (succeeds)
    # 2. create_review fails
    # 3. rollback CAS expects current=VISUAL_PLAN_SETUP
    # To make rollback fail, we simulate concurrent stage change by
    # mutating the run after CAS but before rollback.
    # Easier approach: just force the stage to something else before rollback.

    # We need a more controlled approach. Let's override conditional_update_run
    # on the run_storage to fail on the second call (the rollback).
    original_cas = run_storage.conditional_update_run
    call_count = 0

    async def _cas_that_fails_on_second_call(
        run_id, updates, expected_stages, workspace_id=None
    ):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: the real stage advance
            return await original_cas(run_id, updates, expected_stages, workspace_id=workspace_id)
        # Second call: rollback — simulate concurrent modification
        return False, {"current_stage": "SOMETHING_ELSE"}

    run_storage.conditional_update_run = _cas_that_fails_on_second_call  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="Stage rollback failed"):
        run(
            service.approve_and_advance(
                run_service=run_svc,
                run_id=run_id,
                stage_name="SCRIPT_REVIEW",
                target_stage="VISUAL_PLAN_SETUP",
                workspace_id=1,
            )
        )
