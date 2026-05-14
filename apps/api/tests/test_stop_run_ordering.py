"""Tests for stop_run and delete_run revoke ordering (#510).

Verifies that:
- stop_run: revoke happens AFTER service call succeeds
- delete_run: celery IDs captured BEFORE delete, revoked AFTER delete succeeds
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient

from creator_service.run_service import ConflictError
from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.main import app


class _FakeRun:
    def __init__(self, run_id: int = 1):
        self.id = run_id
        self.project_id = 1


class _CallTracker:
    def __init__(self):
        self.order: list[str] = []


@pytest.fixture(autouse=True)
def _override_run_access():
    user = CurrentUser(user_id=1, workspace_id=1)

    async def _fake(run_id: int):
        return user, _FakeRun(run_id)

    app.dependency_overrides[require_run_access] = _fake
    yield
    app.dependency_overrides.pop(require_run_access, None)


# --- stop_run tests ---

@pytest.mark.asyncio
async def test_stop_run_revokes_after_service_call(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    tracker = _CallTracker()
    mock_updated = MagicMock()
    mock_updated.model_dump.return_value = {"id": 1, "status": "stopped"}

    async def _mock_stop_run(run_id, workspace_id):
        tracker.order.append("stop_run")
        return mock_updated

    async def _mock_revoke(run_id):
        tracker.order.append("revoke")

    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.stop_run", _mock_stop_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._revoke_active_tasks_for_run", _mock_revoke)

    response = await client.post("/api/creator/runs/1/stop")
    assert response.status_code == 200
    assert tracker.order == ["stop_run", "revoke"]


@pytest.mark.asyncio
async def test_stop_run_does_not_revoke_on_conflict(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    revoke_called = False

    async def _mock_stop_run(run_id, workspace_id):
        raise ConflictError("already stopped")

    async def _mock_revoke(run_id):
        nonlocal revoke_called
        revoke_called = True

    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.stop_run", _mock_stop_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._revoke_active_tasks_for_run", _mock_revoke)

    response = await client.post("/api/creator/runs/1/stop")
    assert response.status_code == 409
    assert revoke_called is False


# --- delete_run tests ---

@pytest.mark.asyncio
async def test_delete_run_captures_ids_before_delete_revokes_after(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Celery IDs must be captured BEFORE delete (CASCADE removes rows), then revoked AFTER."""
    tracker = _CallTracker()

    async def _mock_collect(run_id):
        tracker.order.append("collect_ids")
        return ["celery-id-1", "celery-id-2"]

    async def _mock_delete_run(run_id, workspace_id):
        tracker.order.append("delete_run")
        return True

    async def _mock_revoke_ids(celery_ids, run_id):
        tracker.order.append("revoke_ids")
        assert celery_ids == ["celery-id-1", "celery-id-2"]

    async def _mock_delete_artifacts(run_id):
        tracker.order.append("delete_artifacts")

    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run", _mock_delete_artifacts)

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 200
    assert tracker.order == ["collect_ids", "delete_run", "revoke_ids", "delete_artifacts"]


@pytest.mark.asyncio
async def test_delete_run_does_not_revoke_on_failure(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    revoke_called = False

    async def _mock_collect(run_id):
        return ["celery-id-1"]

    async def _mock_delete_run(run_id, workspace_id):
        raise ValueError("Run not found")

    async def _mock_revoke_ids(celery_ids, run_id):
        nonlocal revoke_called
        revoke_called = True

    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids)

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 404
    assert revoke_called is False


@pytest.mark.asyncio
async def test_delete_run_not_deleted_skips_revoke(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """If delete_run returns False, no revoke or artifact cleanup should happen."""
    revoke_called = False
    artifacts_called = False

    async def _mock_collect(run_id):
        return ["celery-id-1"]

    async def _mock_delete_run(run_id, workspace_id):
        return False

    async def _mock_revoke_ids(celery_ids, run_id):
        nonlocal revoke_called
        revoke_called = True

    async def _mock_delete_artifacts(run_id):
        nonlocal artifacts_called
        artifacts_called = True

    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run", _mock_delete_artifacts)

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 404
    assert revoke_called is False
    assert artifacts_called is False
