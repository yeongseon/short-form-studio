import asyncio

import pytest
from creator_service.postgres_project_storage import PostgresProjectStorage
from creator_service.postgres_render_storage import PostgresRenderStorage
from creator_service.postgres_run_storage import PostgresRunStorage
from creator_domain.exceptions import ConflictError
from creator_service.run_service import InMemoryRunStorage, RunService


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


def test_postgres_run_storage_conditional_update_scopes_by_workspace(monkeypatch):
    storage = PostgresRunStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_one(query: str, *args: object):
        calls.append((query, args))
        return None

    monkeypatch.setattr("creator_service.postgres_run_storage.fetch_one", _fake_fetch_one)

    ok, row = run(
        storage.conditional_update_run(
            7,
            {"current_stage": "SCRIPT_GENERATING"},
            frozenset({"SCRIPT_REVIEW"}),
            workspace_id=42,
        )
    )

    assert ok is False
    assert row is None
    assert len(calls) == 2
    assert "UPDATE creator_runs SET" in calls[0][0]
    assert "workspace_id = $" in calls[0][0]
    assert calls[0][1] == (7, ["SCRIPT_REVIEW"], "SCRIPT_GENERATING", 42)
    assert "SELECT * FROM creator_runs WHERE id = $1 AND workspace_id = $2" in calls[1][0]
    assert calls[1][1] == (7, 42)


def test_postgres_run_storage_merge_model_defaults_scopes_by_workspace(monkeypatch):
    storage = PostgresRunStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_one(query: str, *args: object):
        calls.append((query, args))
        return None

    monkeypatch.setattr("creator_service.postgres_run_storage.fetch_one", _fake_fetch_one)

    with pytest.raises(ValueError, match="Run 9 not found"):
        run(storage.merge_model_defaults(9, '{"script_model":"a"}', workspace_id=33))

    assert len(calls) == 1
    assert "WHERE id = $1 AND workspace_id = $3" in calls[0][0]
    assert calls[0][1] == (9, '{"script_model":"a"}', 33)


def test_postgres_run_storage_delete_run_scopes_by_workspace(monkeypatch):
    storage = PostgresRunStorage()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fake_fetch_one(query: str, *args: object):
        calls.append((query, args))
        return None

    monkeypatch.setattr("creator_service.postgres_run_storage.fetch_one", _fake_fetch_one)

    deleted = run(storage.delete_run(12, workspace_id=5))

    assert deleted is False
    assert len(calls) == 1
    assert (
        "DELETE FROM creator_runs WHERE id = $1 AND workspace_id = $2 RETURNING id" in calls[0][0]
    )
    assert calls[0][1] == (12, 5)


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


def test_inmemory_conditional_update_run_scopes_by_workspace():
    storage = InMemoryRunStorage()
    created = run(
        storage.create_run(
            {
                "project_id": 1,
                "workspace_id": 100,
                "current_stage": "SCRIPT_REVIEW",
                "status": "pending",
                "style_preset": "default",
            }
        )
    )

    ok, row = run(
        storage.conditional_update_run(
            created["id"],
            {"current_stage": "SCRIPT_GENERATING"},
            frozenset({"SCRIPT_REVIEW"}),
            workspace_id=200,
        )
    )

    assert ok is False
    assert row is None
    unchanged = run(storage.get_run(created["id"], workspace_id=100))
    assert unchanged is not None
    assert unchanged["current_stage"] == "SCRIPT_REVIEW"


def test_inmemory_merge_model_defaults_and_delete_run_scope_by_workspace():
    storage = InMemoryRunStorage()
    created = run(
        storage.create_run(
            {
                "project_id": 1,
                "workspace_id": 100,
                "current_stage": "IDEA_READY",
                "status": "pending",
                "style_preset": "default",
                "model_defaults_json": "{}",
            }
        )
    )

    with pytest.raises(ValueError, match=f"Run {created['id']} not found"):
        run(
            storage.merge_model_defaults(
                created["id"],
                '{"script_model":"x"}',
                workspace_id=200,
            )
        )

    deleted = run(storage.delete_run(created["id"], workspace_id=200))
    assert deleted is False
    assert run(storage.get_run(created["id"], workspace_id=100)) is not None


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
