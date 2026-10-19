from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from creator_service.postgres_stage_review_storage import PostgresStageReviewStorage


class _Connection:
    def __init__(self) -> None:
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        return {
            "id": 41, "run_id": args[0], "stage_name": args[1],
            "review_status": args[2], "reviewer": args[3], "notes": args[4],
        }

    async def execute(self, query: str, *args: object) -> str:
        self.execute_calls.append((query, args))
        return "INSERT 0 2"

    async def fetchval(self, query: str, *args: object):
        return 17

    def transaction(self):
        @asynccontextmanager
        async def context():
            yield

        return context()


class _Pool:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def acquire(self):
        @asynccontextmanager
        async def context():
            yield self.connection

        return context()


@pytest.mark.asyncio
async def test_timeline_approval_persists_exact_revision_assets(monkeypatch) -> None:
    # Given an approved Timeline review with an exact revision in its notes.
    connection = _Connection()

    async def get_pool():
        return _Pool(connection)

    monkeypatch.setattr("creator_service.postgres_stage_review_storage.db.get_pool", get_pool)

    # When the approval is persisted.
    await PostgresStageReviewStorage().create_review({
        "run_id": 7, "stage_name": "TIMELINE_REVIEW", "review_status": "approved",
        "reviewer": "human", "notes": '{"timeline_id":"timeline-1","revision":3}',
    })

    # Then the same transaction maps only that persisted revision's asset ids.
    query, args = connection.execute_calls[1]
    assert "creator_approved_timeline_assets" in query
    assert "t.revision = $4" in query
    assert args == (41, 7, "timeline-1", 3)


@pytest.mark.asyncio
async def test_non_timeline_approval_does_not_persist_asset_mapping(monkeypatch) -> None:
    # Given another review stage with Timeline-shaped notes.
    connection = _Connection()

    async def get_pool():
        return _Pool(connection)

    monkeypatch.setattr("creator_service.postgres_stage_review_storage.db.get_pool", get_pool)

    # When its approval is persisted.
    await PostgresStageReviewStorage().create_review({
        "run_id": 7, "stage_name": "SCRIPT_REVIEW", "review_status": "approved",
        "reviewer": "human", "notes": '{"timeline_id":"timeline-1","revision":3}',
    })

    # Then no Timeline asset mapping is created.
    assert connection.execute_calls == []
