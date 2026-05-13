import asyncio

from creator_service.postgres_project_storage import PostgresProjectStorage
from creator_service.postgres_render_storage import PostgresRenderStorage
from creator_service.postgres_run_storage import PostgresRunStorage


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
