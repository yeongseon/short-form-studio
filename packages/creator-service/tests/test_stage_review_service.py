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
