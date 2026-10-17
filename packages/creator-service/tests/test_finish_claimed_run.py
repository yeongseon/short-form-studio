from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from creator_service import postgres_task_tracking_storage as storage_module
from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage


class _Context(AbstractAsyncContextManager):
    def __init__(self, value: object) -> None:
        self.value = value

    async def __aenter__(self) -> object:
        return self.value

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_finish_claimed_run_retains_claim_when_run_transition_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a matching task claim whose run has concurrently left the expected stage.
    connection = SimpleNamespace(
        transaction=lambda: _Context(None),
        fetchrow=AsyncMock(side_effect=[{"id": 7}, None]),
    )
    pool = SimpleNamespace(acquire=lambda: _Context(connection))

    async def get_pool() -> object:
        return pool

    monkeypatch.setattr(storage_module.db, "get_pool", get_pool)

    # When the old claim attempts the atomic run/task finalization.
    accepted = await PostgresTaskTrackingStorage().finish_claimed_run(
        "delivery-1",
        "claim-old",
        "success",
        SimpleNamespace(),
        42,
        {"current_stage": "FINAL_REVIEW", "status": "paused"},
        frozenset({"RENDER_GENERATING"}),
        frozenset({"cancelled"}),
    )

    # Then the task row is not finalized after the run CAS loses.
    assert accepted is False
    assert connection.fetchrow.await_count == 2
