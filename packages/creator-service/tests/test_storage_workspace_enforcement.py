import asyncio

import pytest
from creator_service.postgres_project_storage import PostgresProjectStorage
from creator_service.postgres_render_storage import PostgresRenderStorage
from creator_service.postgres_run_storage import PostgresRunStorage
from creator_service.run_service import ConflictError, InMemoryRunStorage, RunService


def run(coro):
    return asyncio.run(coro)


def test_postgres_run_storage_get_run_scopes_by_workspace(monkeypatch):
    storage = PostgresRunStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_one(query: str, *args: object):
        calls.append((query, args))
        return None

    monkeypatch.setattr("creator_service.postgres_run_storage.fetch_one", _fake_fetch_one)

    row = run(storage.get_run(101, workspace_id=999))

    assert row is None
    assert len(calls) == 1
    assert "WHERE id = $1 AND workspace_id = $2" in calls[0][0]
    assert calls[0][1] == (101, 999)


def test_postgres_run_storage_update_run_scopes_by_workspace(monkeypatch):
    storage = PostgresRunStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_one(query: str, *args: object):
        calls.append((query, args))
        return None

    monkeypatch.setattr("creator_service.postgres_run_storage.fetch_one", _fake_fetch_one)

    try:
        run(storage.update_run(5, {"status": "running"}, workspace_id=77))
    except ValueError:
        pass

    assert len(calls) == 1
    assert "WHERE id = $1 AND workspace_id = $" in calls[0][0]
    assert calls[0][1] == (5, "running", 77)


def test_postgres_project_storage_fetch_project_scopes_by_workspace(monkeypatch):
    storage = PostgresProjectStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_one(query: str, *args: object):
        calls.append((query, args))
        return None

    monkeypatch.setattr("creator_service.postgres_project_storage.fetch_one", _fake_fetch_one)

    row = run(storage.fetch_project(42, workspace_id=2))

    assert row is None
    assert len(calls) == 1
    assert "WHERE id = $1 AND workspace_id = $2" in calls[0][0]
    assert calls[0][1] == (42, 2)


def test_postgres_render_storage_list_by_run_scopes_by_workspace(monkeypatch):
    storage = PostgresRenderStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_all(query: str, *args: object):
        calls.append((query, args))
        return []

    monkeypatch.setattr("creator_service.postgres_render_storage.fetch_all", _fake_fetch_all)

    rows = run(storage.list_by_run(9, workspace_id=123))

    assert rows == []
    assert len(calls) == 1
    assert "EXISTS (" in calls[0][0]
    assert "creator_runs" in calls[0][0]
    assert "workspace_id = $2" in calls[0][0]
    assert calls[0][1] == (9, 123)


def test_inmemory_run_storage_enforces_workspace_filtering_behavior():
    storage = InMemoryRunStorage()

    run_a = run(
        storage.create_run(
            {
                "project_id": 1,
                "workspace_id": 11,
                "current_stage": "IDEA_READY",
                "status": "pending",
                "style_preset": "default",
            }
        )
    )
    run_b = run(
        storage.create_run(
            {
                "project_id": 2,
                "workspace_id": 22,
                "current_stage": "IDEA_READY",
                "status": "pending",
                "style_preset": "default",
            }
        )
    )

    assert run(storage.get_run(run_a["id"], workspace_id=11)) is not None
    assert run(storage.get_run(run_a["id"], workspace_id=22)) is None

    rows = run(storage.list_runs_by_workspace(11))
    assert [row["id"] for row in rows] == [run_a["id"]]
    assert rows[0]["workspace_id"] == 11
    assert run(storage.get_run(run_b["id"], workspace_id=11)) is None


def test_run_service_advance_stage_conflict_with_inmemory_storage_cas(monkeypatch):
    storage = InMemoryRunStorage()
    service = RunService(storage)

    created = run(
        service.create_run(
            project_id=99,
            model_defaults=None,
            style_preset="default",
            current_stage="IDEA_READY",
            workspace_id=7,
        )
    )

    original_update = storage.update_run

    async def conflicting_update_run(
        run_id: int,
        updates: dict[str, object],
        *,
        workspace_id: int | None = None,
        expected_version: int | None = None,
    ):
        if expected_version is not None:
            await original_update(run_id, {"status": "running"}, workspace_id=7)
        return await original_update(
            run_id,
            updates,
            workspace_id=workspace_id,
            expected_version=expected_version,
        )

    monkeypatch.setattr(storage, "update_run", conflicting_update_run)

    with pytest.raises(ConflictError, match="stale version"):
        run(service.advance_stage(created.id, "SCRIPT_GENERATING", workspace_id=7))
