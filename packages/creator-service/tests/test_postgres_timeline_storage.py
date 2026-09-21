"""SF-28: PostgresTimelineStorage SQL contract.

No live DB in unit CI; per repo convention (test_storage_workspace_enforcement)
these assert the SQL is workspace/project/revision-scoped and carries the right
params, plus a fake fetch_one that simulates the update-first-then-insert CTE
branch behavior so a regression to insert-only (which never updates existing
rows) is caught without a live database.
"""

from __future__ import annotations

import asyncio

from creator_service.postgres_timeline_storage import PostgresTimelineStorage


def run(coro):
    return asyncio.run(coro)


def test_save_sql_is_scoped_by_project_workspace_and_revision(monkeypatch) -> None:
    storage = PostgresTimelineStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_one(query: str, *args: object):
        calls.append((query, args))
        return None

    monkeypatch.setattr(
        "creator_service.postgres_timeline_storage.fetch_one", _fake_fetch_one
    )

    run(
        storage.save_timeline(
            project_id=1,
            workspace_id=9,
            timeline_id="t-1",
            segments_json="[]",
            expected_revision=2,
        )
    )

    query, args = calls[0]
    # authorization + workspace + optimistic revision must all be in the SQL
    assert "creator_projects" in query
    assert "workspace_id = $2" in query
    assert "revision = $5" in query
    # update-first CTE + guarded first-write insert (not insert-only)
    assert "UPDATE creator_timelines" in query
    assert "INSERT INTO creator_timelines" in query
    assert "revision = revision + 1" in query
    assert args == (1, 9, "t-1", "[]", 2)


def test_load_sql_is_workspace_scoped(monkeypatch) -> None:
    storage = PostgresTimelineStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_one(query: str, *args: object):
        calls.append((query, args))
        return None

    monkeypatch.setattr(
        "creator_service.postgres_timeline_storage.fetch_one", _fake_fetch_one
    )

    run(storage.load_timeline(project_id=3, workspace_id=4))

    query, args = calls[0]
    assert "WHERE project_id = $1 AND workspace_id = $2" in query
    assert args == (3, 4)


class _FakeTimelineTable:
    """Simulates the update-first/insert CTE against a one-row-per-project table."""

    def __init__(self) -> None:
        self.rows: dict[int, dict[str, object]] = {}

    async def fetch_one(self, query: str, *args: object):
        project_id, workspace_id, timeline_id, segments_json, expected_revision = args
        existing = self.rows.get(project_id)  # type: ignore[arg-type]
        # UPDATE branch: existing row, workspace + revision match
        if (
            existing is not None
            and existing["workspace_id"] == workspace_id
            and existing["revision"] == expected_revision
        ):
            existing = {
                **existing,
                "timeline_id": timeline_id,
                "segments_json": segments_json,
                "revision": existing["revision"] + 1,
            }
            self.rows[project_id] = existing  # type: ignore[index]
            return dict(existing)
        # INSERT branch: no row, first write only
        if existing is None and expected_revision == 0:
            row = {
                "project_id": project_id,
                "workspace_id": workspace_id,
                "timeline_id": timeline_id,
                "revision": 1,
                "segments_json": segments_json,
            }
            self.rows[project_id] = row  # type: ignore[index]
            return dict(row)
        return None


def test_cte_branches_first_write_update_and_stale(monkeypatch) -> None:
    storage = PostgresTimelineStorage()
    fake = _FakeTimelineTable()
    monkeypatch.setattr(
        "creator_service.postgres_timeline_storage.fetch_one", fake.fetch_one
    )

    first = run(
        storage.save_timeline(
            project_id=1, workspace_id=1, timeline_id="t", segments_json="[]",
            expected_revision=0,
        )
    )
    assert first is not None and first["revision"] == 1

    # matching-revision update must succeed and increment (the regression Oracle caught)
    updated = run(
        storage.save_timeline(
            project_id=1, workspace_id=1, timeline_id="t", segments_json="[1]",
            expected_revision=1,
        )
    )
    assert updated is not None and updated["revision"] == 2

    # stale write must return None
    stale = run(
        storage.save_timeline(
            project_id=1, workspace_id=1, timeline_id="t", segments_json="[2]",
            expected_revision=1,
        )
    )
    assert stale is None

    # first-write with nonzero expected must return None
    nonzero = run(
        storage.save_timeline(
            project_id=2, workspace_id=1, timeline_id="t", segments_json="[]",
            expected_revision=5,
        )
    )
    assert nonzero is None

    # cross-workspace update must return None
    cross = run(
        storage.save_timeline(
            project_id=1, workspace_id=2, timeline_id="t", segments_json="[]",
            expected_revision=2,
        )
    )
    assert cross is None
