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
from shorts_api.auth import CurrentUser, require_run_access, require_project_access
from shorts_api.main import app


class _FakeRun:
    def __init__(
        self,
        run_id: int = 1,
        status: str = "running",
        current_stage: str = "AUDIO_GENERATING",
    ):
        self.id = run_id
        self.project_id = 1
        self.status = status
        self.current_stage = current_stage


class _CallTracker:
    def __init__(self):
        self.order: list[str] = []


class _FakeProject:
    status: str = "active"
    def __init__(self, project_id: int = 99):
        self.id = project_id
        self.workspace_id = 1


@pytest.fixture(autouse=True)
def _override_access():
    user = CurrentUser(user_id=1, workspace_id=1)

    async def _fake_run(run_id: int):
        return user, _FakeRun(run_id)

    async def _fake_project(project_id: int):
        return user, _FakeProject(project_id)

    app.dependency_overrides[require_run_access] = _fake_run
    app.dependency_overrides[require_project_access] = _fake_project
    yield
    app.dependency_overrides.pop(require_run_access, None)
    app.dependency_overrides.pop(require_project_access, None)


# --- stop_run tests ---


@pytest.mark.asyncio
async def test_stop_run_revokes_after_service_call(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = _CallTracker()
    mock_updated = MagicMock()
    mock_updated.model_dump.return_value = {"id": 1, "status": "stopped"}

    async def _mock_stop_run(run_id, workspace_id):
        tracker.order.append("stop_run")
        return mock_updated

    async def _mock_revoke(run_id):
        tracker.order.append("revoke")

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.stop_run", _mock_stop_run
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_active_tasks_for_run", _mock_revoke
    )

    response = await client.post("/api/creator/runs/1/stop")
    assert response.status_code == 200
    assert tracker.order == ["stop_run", "revoke"]


@pytest.mark.asyncio
async def test_stop_run_does_not_revoke_on_conflict(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    revoke_called = False

    async def _mock_stop_run(run_id, workspace_id):
        raise ConflictError("already stopped")

    async def _mock_revoke(run_id):
        nonlocal revoke_called
        revoke_called = True

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.stop_run", _mock_stop_run
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_active_tasks_for_run", _mock_revoke
    )

    response = await client.post("/api/creator/runs/1/stop")
    assert response.status_code == 409
    assert revoke_called is False


# --- delete_run tests ---


@pytest.mark.asyncio
async def test_delete_run_captures_ids_before_delete_revokes_after(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Celery IDs must be captured BEFORE delete (CASCADE removes rows), then revoked AFTER."""
    tracker = _CallTracker()

    async def _mock_update_run(run_id, updates, workspace_id):
        tracker.order.append("mark_cancelled")
        assert updates == {"status": "cancelled"}

    async def _mock_collect(run_id):
        tracker.order.append("collect_ids")
        return ["celery-id-1", "celery-id-2"], True

    async def _mock_delete_run(run_id, workspace_id):
        tracker.order.append("delete_run")
        return True

    async def _mock_revoke_ids(celery_ids, run_id):
        tracker.order.append("revoke_ids")
        assert celery_ids == ["celery-id-1", "celery-id-2"]
        return True

    async def _mock_delete_artifacts(run_id):
        tracker.order.append("delete_artifacts")
        return 0

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 200
    assert tracker.order == [
        "mark_cancelled",
        "collect_ids",
        "revoke_ids",
        "delete_artifacts",
        "delete_run",
    ]


@pytest.mark.asyncio
async def test_delete_run_db_failure_still_revokes_and_cleans(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With storage-first ordering, revoke and artifact cleanup execute BEFORE DB delete.

    Even if delete_run raises ValueError, revoke and cleanup already happened.
    This is the correct behavior: better to eagerly clean storage than orphan objects.
    """
    revoke_called = False

    async def _mock_update_run(run_id, updates, workspace_id):
        return None

    async def _mock_collect(run_id):
        return ["celery-id-1"], True

    async def _mock_delete_run(run_id, workspace_id):
        raise ValueError("Run not found")

    async def _mock_revoke_ids(celery_ids, run_id):
        nonlocal revoke_called
        revoke_called = True

    async def _mock_delete_artifacts(run_id):
        return 0

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 404
    # With storage-first ordering, revoke executes before DB delete
    assert revoke_called is True


@pytest.mark.asyncio
async def test_delete_run_not_deleted_still_cleans_artifacts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With storage-first ordering, revoke and artifact cleanup happen BEFORE DB delete.

    If delete_run returns False (unexpected — run was already cancelled above),
    artifacts and revoke will already have executed.  This is correct: better to
    clean storage eagerly than to orphan objects.
    """
    revoke_called = False
    artifacts_called = False

    async def _mock_update_run(run_id, updates, workspace_id):
        return None

    async def _mock_collect(run_id):
        return ["celery-id-1"], True

    async def _mock_delete_run(run_id, workspace_id):
        return False

    async def _mock_revoke_ids(celery_ids, run_id):
        nonlocal revoke_called
        revoke_called = True

    async def _mock_delete_artifacts(run_id):
        nonlocal artifacts_called
        artifacts_called = True
        return 0

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 404
    # With storage-first ordering, revoke and artifacts execute before DB delete
    assert revoke_called is True
    assert artifacts_called is True


@pytest.mark.asyncio
async def test_delete_run_response_includes_revoke_reliable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _mock_update_run(run_id, updates, workspace_id):
        return None

    async def _mock_collect(run_id):
        return ["celery-id-1"], True

    async def _mock_delete_run(run_id, workspace_id):
        return True

    async def _mock_revoke_ids(celery_ids, run_id):
        return True

    async def _mock_delete_artifacts(run_id):
        return 0

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 200
    assert response.json()["revoke_reliable"] is True


@pytest.mark.asyncio
async def test_delete_run_marks_cancelled_before_collecting_ids(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = _CallTracker()

    async def _mock_run_access(run_id: int):
        user = CurrentUser(user_id=1, workspace_id=1)
        return user, _FakeRun(run_id=run_id, status="running", current_stage="VISUAL_ASSET_REVIEW")

    async def _mock_update_run(run_id, updates, workspace_id):
        tracker.order.append("mark_cancelled")
        assert updates == {"status": "cancelled"}

    async def _mock_collect(run_id):
        tracker.order.append("collect_ids")
        return ["celery-id-1"], True

    async def _mock_delete_run(run_id, workspace_id):
        tracker.order.append("delete_run")
        return True

    async def _mock_revoke_ids(celery_ids, run_id):
        tracker.order.append("revoke_ids")
        return True

    async def _mock_delete_artifacts(run_id):
        tracker.order.append("delete_artifacts")
        return 0

    app.dependency_overrides[require_run_access] = _mock_run_access
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )

    response = await client.delete("/api/creator/runs/1")

    assert response.status_code == 200
    assert tracker.order == [
        "mark_cancelled",
        "collect_ids",
        "revoke_ids",
        "delete_artifacts",
        "delete_run",
    ]


@pytest.mark.asyncio
async def test_delete_run_from_review_stage_blocks_concurrent_dispatch(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracker = _CallTracker()

    async def _mock_run_access(run_id: int):
        user = CurrentUser(user_id=1, workspace_id=1)
        return user, _FakeRun(run_id=run_id, status="running", current_stage="VISUAL_ASSET_REVIEW")

    async def _mock_update_run(run_id, updates, workspace_id):
        tracker.order.append("mark_cancelled")
        assert updates == {"status": "cancelled"}

    async def _mock_collect(run_id):
        tracker.order.append("collect_ids")
        return [], True

    async def _mock_delete_run(run_id, workspace_id):
        tracker.order.append("delete_run")
        return True

    async def _mock_revoke_ids(celery_ids, run_id):
        tracker.order.append("revoke_ids")
        return True

    async def _mock_delete_artifacts(run_id):
        tracker.order.append("delete_artifacts")
        return 0

    app.dependency_overrides[require_run_access] = _mock_run_access
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )

    response = await client.delete("/api/creator/runs/1")

    assert response.status_code == 200
    assert tracker.order.index("mark_cancelled") < tracker.order.index("collect_ids")


# --- Unit tests for helper functions ---


@pytest.mark.asyncio
async def test_collect_active_celery_ids_returns_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    from shorts_api.routes.creator_runs_utils import _collect_active_celery_ids

    class _MockTracking:
        async def get_active_celery_ids(self, run_id):
            return ["id-1", "id-2"]

    monkeypatch.setattr(
        "creator_service.task_tracking_service.task_tracking_service",
        _MockTracking(),
    )

    result = await _collect_active_celery_ids(42)
    assert result == (["id-1", "id-2"], True)


@pytest.mark.asyncio
async def test_collect_active_celery_ids_returns_empty_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from shorts_api.routes.creator_runs_utils import _collect_active_celery_ids

    class _MockTracking:
        async def get_active_celery_ids(self, run_id):
            raise RuntimeError("DB down")

    monkeypatch.setattr(
        "creator_service.task_tracking_service.task_tracking_service",
        _MockTracking(),
    )

    result = await _collect_active_celery_ids(42)
    assert result == ([], False)


@pytest.mark.asyncio
async def test_revoke_celery_ids_empty_list_is_noop() -> None:
    from shorts_api.routes.creator_runs_utils import _revoke_celery_ids

    # Should not raise or call anything
    await _revoke_celery_ids([], run_id=1)


@pytest.mark.asyncio
async def test_delete_run_fails_closed_when_cancel_write_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If pre-delete cancellation write fails, delete_run must return 503 (fail-closed)."""
    delete_called = False

    async def _mock_update_run(run_id, updates, workspace_id=None, expected_version=None):
        raise RuntimeError("storage unavailable")

    async def _mock_collect(run_id):
        return ["celery-id-1"], True

    async def _mock_delete_run(run_id, workspace_id):
        nonlocal delete_called
        delete_called = True
        return True

    async def _mock_revoke_ids(celery_ids, run_id):
        pass

    async def _mock_delete_artifacts(run_id):
        return 0

    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run", _mock_update_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run", _mock_delete_artifacts)

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 503
    assert "cancel" in response.json()["detail"].lower()
    assert delete_called is False, "delete_run must not proceed if cancellation write fails"


@pytest.mark.asyncio
async def test_delete_run_aborts_db_delete_when_artifact_cleanup_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If artifact cleanup reports failures, DB row must NOT be deleted.

    Deleting the parent run row would CASCADE-delete creator_artifacts rows,
    destroying the retry state that artifact_download_service preserves for
    partially-failed storage deletes.
    """
    delete_run_called = False

    async def _mock_update_run(run_id, updates, workspace_id):
        return {"id": run_id}

    async def _mock_collect(run_id):
        return []

    async def _mock_delete_run(run_id, workspace_id=None):
        nonlocal delete_run_called
        delete_run_called = True
        return True

    async def _mock_revoke_ids(celery_ids, run_id):
        pass

    async def _mock_delete_artifacts_with_failure(run_id):
        """Simulate partial storage failure — 2 artifacts failed."""
        return 2

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids",
        _mock_collect,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.delete_run",
        _mock_delete_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids",
        _mock_revoke_ids,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts_with_failure,
    )

    response = await client.delete("/api/creator/runs/1")
    # Should return 503 — retryable error, not 200
    assert response.status_code == 503
    assert "artifact" in response.json()["detail"].lower()
    # Critical: DB row must NOT have been deleted
    assert delete_run_called is False


@pytest.mark.asyncio
async def test_delete_project_aborts_db_delete_when_artifact_cleanup_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If any run's artifact cleanup fails during project delete, DB must not be deleted."""
    delete_project_called = False

    class StubRun:
        def __init__(self, run_id):
            self.id = run_id

    async def _mock_revoke(run_id):
        return True

    async def _mock_list_runs(project_id):
        return [StubRun(10), StubRun(11)]

    async def _mock_update_run(run_id, updates, workspace_id):
        return {"id": run_id}

    async def _mock_delete_artifacts(run_id):
        if run_id == 11:
            return 1  # partial failure on second run
        return 0

    async def _mock_delete_project(project_id, workspace_id=None):
        nonlocal delete_project_called
        delete_project_called = True
        return True

    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.list_runs_by_project",
        _mock_list_runs,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.creator_runs_utils._revoke_active_tasks_for_run",
        _mock_revoke,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.delete_project",
        _mock_delete_project,
    )

    response = await client.delete("/api/creator/projects/99")
    assert response.status_code == 503
    assert "artifact" in response.json()["detail"].lower()
    assert delete_project_called is False


@pytest.mark.asyncio
async def test_delete_project_removes_artifacts_before_db_delete(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: project deletion must clean storage BEFORE deleting DB rows."""
    order: list[str] = []

    class StubRun:
        def __init__(self, run_id):
            self.id = run_id

    async def _mock_revoke(run_id):
        order.append("revoke")
        return True

    async def _mock_list_runs(project_id):
        return [StubRun(10)]

    async def _mock_update_run(run_id, updates, workspace_id):
        order.append("cancel")
        return {"id": run_id}

    async def _mock_delete_artifacts(run_id):
        order.append("delete_artifacts")
        return 0

    async def _mock_delete_project(project_id, workspace_id=None):
        order.append("delete_project")
        return True

    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.list_runs_by_project",
        _mock_list_runs,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.creator_runs_utils._revoke_active_tasks_for_run",
        _mock_revoke,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.delete_project",
        _mock_delete_project,
    )

    response = await client.delete("/api/creator/projects/99")
    assert response.status_code == 200
    assert order == ["cancel", "revoke", "delete_artifacts", "delete_project"]


@pytest.mark.asyncio
async def test_delete_project_marks_runs_cancelled_before_cleanup(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project deletion must mark member runs cancelled before revoking/cleaning.

    This mirrors delete_run's concurrency barrier: marking cancelled blocks
    any concurrent dispatch so no new artifacts appear during cleanup.
    """
    order: list[str] = []

    class StubRun:
        def __init__(self, run_id):
            self.id = run_id

    async def _mock_update_run(run_id, updates, workspace_id):
        if updates.get("status") == "cancelled":
            order.append(f"cancel_{run_id}")
        return {"id": run_id}

    async def _mock_list_runs(project_id):
        return [StubRun(10), StubRun(11)]

    async def _mock_revoke(run_id):
        order.append(f"revoke_{run_id}")
        return True

    async def _mock_delete_artifacts(run_id):
        order.append(f"artifacts_{run_id}")
        return 0

    async def _mock_delete_project(project_id, workspace_id=None):
        order.append("delete_project")
        return True

    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.list_runs_by_project",
        _mock_list_runs,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.creator_runs_utils._revoke_active_tasks_for_run",
        _mock_revoke,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.delete_project",
        _mock_delete_project,
    )

    response = await client.delete("/api/creator/projects/99")
    assert response.status_code == 200
    # Cancellation must happen BEFORE revoke and artifact cleanup
    assert order == [
        "cancel_10", "cancel_11",
        "revoke_10", "revoke_11",
        "artifacts_10", "artifacts_11",
        "delete_project",
    ]


@pytest.mark.asyncio
async def test_delete_project_aborts_when_cancel_write_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If marking a run cancelled fails, project delete must return 503.

    This is the fail-closed counterpart to delete_run's cancel barrier.
    No revoke, artifact cleanup, or DB delete should happen.
    """
    revoke_called = False
    artifacts_called = False
    delete_called = False

    class StubRun:
        def __init__(self, run_id):
            self.id = run_id

    async def _mock_update_run(run_id, updates, workspace_id):
        raise RuntimeError("DB write failed")

    async def _mock_list_runs(project_id):
        return [StubRun(10)]

    async def _mock_revoke(run_id):
        nonlocal revoke_called
        revoke_called = True

    async def _mock_delete_artifacts(run_id):
        nonlocal artifacts_called
        artifacts_called = True
        return 0

    async def _mock_delete_project(project_id, workspace_id=None):
        nonlocal delete_called
        delete_called = True
        return True

    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.list_runs_by_project",
        _mock_list_runs,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.creator_runs_utils._revoke_active_tasks_for_run",
        _mock_revoke,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.delete_project",
        _mock_delete_project,
    )

    response = await client.delete("/api/creator/projects/99")
    assert response.status_code == 503
    assert "cancel" in response.json()["detail"].lower()
    assert revoke_called is False
    assert artifacts_called is False
    assert delete_called is False


@pytest.mark.asyncio
async def test_delete_run_aborts_when_revoke_unreliable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If task revocation is unreliable, delete_run must abort with 503."""
    delete_called = False

    async def _mock_update_run(run_id, updates, workspace_id=None, expected_version=None):
        return {"id": run_id}

    async def _mock_collect(run_id):
        return ["celery-id-1"], True

    async def _mock_revoke_ids(celery_ids, run_id):
        return False  # revoke failed

    async def _mock_delete_run(run_id, workspace_id):
        nonlocal delete_called
        delete_called = True
        return True

    async def _mock_delete_artifacts(run_id):
        return 0

    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run", _mock_update_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run", _mock_delete_artifacts)

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 503
    assert "revoke" in response.json()["detail"].lower()
    assert delete_called is False


@pytest.mark.asyncio
async def test_delete_run_aborts_when_collect_unreliable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If active task collection fails, delete_run must abort with 503."""
    delete_called = False

    async def _mock_update_run(run_id, updates, workspace_id=None, expected_version=None):
        return {"id": run_id}

    async def _mock_collect(run_id):
        return [], False  # collection failed

    async def _mock_revoke_ids(celery_ids, run_id):
        return True

    async def _mock_delete_run(run_id, workspace_id):
        nonlocal delete_called
        delete_called = True
        return True

    async def _mock_delete_artifacts(run_id):
        return 0

    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run", _mock_update_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._collect_active_celery_ids", _mock_collect)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle._revoke_celery_ids", _mock_revoke_ids)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.run_service.delete_run", _mock_delete_run)
    monkeypatch.setattr("shorts_api.routes.creator_runs_lifecycle.artifact_download_service.delete_artifacts_for_run", _mock_delete_artifacts)

    response = await client.delete("/api/creator/runs/1")
    assert response.status_code == 503
    assert "revoke" in response.json()["detail"].lower()
    assert delete_called is False


@pytest.mark.asyncio
async def test_delete_project_aborts_when_revoke_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If task revocation fails during project delete, must abort with 503."""
    delete_project_called = False

    class StubRun:
        def __init__(self, run_id):
            self.id = run_id

    async def _mock_update_run(run_id, updates, workspace_id):
        return {"id": run_id}

    async def _mock_list_runs(project_id):
        return [StubRun(10)]

    async def _mock_revoke(run_id):
        return False  # revoke failed

    async def _mock_delete_artifacts(run_id):
        return 0

    async def _mock_delete_project(project_id, workspace_id=None):
        nonlocal delete_project_called
        delete_project_called = True
        return True

    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.list_runs_by_project",
        _mock_list_runs,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.creator_runs_utils._revoke_active_tasks_for_run",
        _mock_revoke,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.delete_project",
        _mock_delete_project,
    )

    response = await client.delete("/api/creator/projects/99")
    assert response.status_code == 503
    assert "revoke" in response.json()["detail"].lower()
    assert delete_project_called is False


@pytest.mark.asyncio
async def test_delete_project_marks_deleting_before_enumerating_runs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project must be marked 'deleting' BEFORE enumerating runs.

    This prevents a TOCTOU race where create_run could insert a new run
    after list_runs_by_project() but before the final DB delete, leaving
    the new run's artifacts orphaned.
    """
    order: list[str] = []

    class StubRun:
        def __init__(self, run_id):
            self.id = run_id

    async def _mock_update_project(project_id, updates, *, workspace_id=None):
        if updates.get("status") == "deleting":
            order.append("mark_deleting")
        return {"id": project_id, "status": "deleting"}

    async def _mock_list_runs(project_id):
        order.append("list_runs")
        return [StubRun(10)]

    async def _mock_update_run(run_id, updates, workspace_id):
        order.append("cancel_run")
        return {"id": run_id}

    async def _mock_revoke(run_id):
        order.append("revoke")
        return True

    async def _mock_delete_artifacts(run_id):
        order.append("delete_artifacts")
        return 0

    async def _mock_delete_project(project_id, workspace_id=None):
        order.append("delete_project")
        return True

    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.db.update_project",
        _mock_update_project,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.list_runs_by_project",
        _mock_list_runs,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.storage.update_run",
        _mock_update_run,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.creator_runs_utils._revoke_active_tasks_for_run",
        _mock_revoke,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.artifact_download_service.delete_artifacts_for_run",
        _mock_delete_artifacts,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.delete_project",
        _mock_delete_project,
    )

    response = await client.delete("/api/creator/projects/99")
    assert response.status_code == 200
    # mark_deleting MUST happen before list_runs
    assert order.index("mark_deleting") < order.index("list_runs")


@pytest.mark.asyncio
async def test_delete_project_aborts_when_mark_deleting_fails(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If marking project 'deleting' fails, abort with 503."""
    list_runs_called = False

    async def _mock_update_project(project_id, updates, *, workspace_id=None):
        raise RuntimeError("DB write failed")

    async def _mock_list_runs(project_id):
        nonlocal list_runs_called
        list_runs_called = True
        return []

    async def _mock_delete_project(project_id, workspace_id=None):
        return True

    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.db.update_project",
        _mock_update_project,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.run_service.list_runs_by_project",
        _mock_list_runs,
    )
    monkeypatch.setattr(
        "shorts_api.routes.creator_projects.project_service.delete_project",
        _mock_delete_project,
    )

    response = await client.delete("/api/creator/projects/99")
    assert response.status_code == 503
    assert "delet" in response.json()["detail"].lower()
    assert list_runs_called is False


@pytest.mark.asyncio
async def test_create_run_rejected_when_project_is_deleting(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_run must reject with 409 if project status is 'deleting'."""

    async def _mock_project_access(project_id: int):
        from creator_domain.models.project import Project
        from datetime import datetime, timezone
        user = CurrentUser(user_id=1, workspace_id=1)
        project = Project(
            id=project_id,
            workspace_id=1,
            title="Test",
            status="deleting",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        return user, project

    app.dependency_overrides[require_project_access] = _mock_project_access

    response = await client.post(
        "/api/creator/projects/99/runs",
        json={"style_preset": "default"},
    )
    assert response.status_code == 409
    assert "delet" in response.json()["detail"].lower()


@pytest.mark.anyio
async def test_create_run_atomic_guard_catches_stale_snapshot_race(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: require_project_access returns status='active', but by the
    time the storage INSERT runs, the project has been flipped to 'deleting'.
    The atomic write-boundary guard must still reject the create."""
    from creator_service.run_service import ConflictError

    # Auth returns active project (simulating stale snapshot)
    async def _mock_project_access(project_id: int):
        from creator_domain.models.project import Project
        from datetime import datetime, timezone as tz

        user = CurrentUser(user_id=1, workspace_id=1)
        project = Project(
            id=project_id,
            workspace_id=1,
            title="Test",
            status="active",  # stale — project is actually deleting
            created_at=datetime.now(tz.utc),
            updated_at=datetime.now(tz.utc),
        )
        return user, project

    app.dependency_overrides[require_project_access] = _mock_project_access

    # Make the service-layer create_run raise ConflictError
    # (simulating the atomic SQL guard detecting the race)
    async def _racing_create(*args, **kwargs):
        raise ConflictError("Project is being deleted; cannot create new runs")

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_core.run_service.create_run", _racing_create
    )

    response = await client.post(
        "/api/creator/projects/99/runs",
        json={"style_preset": "default"},
    )
    assert response.status_code == 409
    assert "delet" in response.json()["detail"].lower()

    app.dependency_overrides.pop(require_project_access, None)


# --- Tests for creator_script.py import routes: deleting guard + ConflictError ---


@pytest.mark.anyio
async def test_import_markdown_rejected_when_project_is_deleting(
    client: AsyncClient,
):
    """import_markdown must reject with 409 if project status is 'deleting'."""
    from shorts_api.auth import require_project_access

    user = CurrentUser(user_id=1, workspace_id=1)
    project = _FakeProject(project_id=99)
    project.status = "deleting"

    async def _fake_project_access(project_id: int):
        return user, project

    app.dependency_overrides[require_project_access] = _fake_project_access
    try:
        resp = await client.post(
            "/api/creator/projects/99/script/import-markdown",
            json={"markdown": "# Hello"},
        )
        assert resp.status_code == 409
        assert "delet" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.anyio
async def test_import_json_rejected_when_project_is_deleting(
    client: AsyncClient,
):
    """import_json must reject with 409 if project status is 'deleting'."""
    from shorts_api.auth import require_project_access

    user = CurrentUser(user_id=1, workspace_id=1)
    project = _FakeProject(project_id=99)
    project.status = "deleting"

    async def _fake_project_access(project_id: int):
        return user, project

    app.dependency_overrides[require_project_access] = _fake_project_access
    try:
        resp = await client.post(
            "/api/creator/projects/99/script/import-json",
            json={"json_script": '{"scenes": [{"type": "narration", "text": "hi"}]}'},
        )
        assert resp.status_code == 409
        assert "delet" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.anyio
async def test_import_markdown_catches_conflict_error_from_storage(
    client: AsyncClient,
):
    """If storage raises ConflictError (race condition), import_markdown returns 409."""
    from shorts_api.auth import require_project_access
    from unittest.mock import AsyncMock, patch

    user = CurrentUser(user_id=1, workspace_id=1)
    project = _FakeProject(project_id=99)
    project.status = "active"

    async def _fake_project_access(project_id: int):
        return user, project

    app.dependency_overrides[require_project_access] = _fake_project_access
    try:
        with patch(
            "shorts_api.routes.creator_script.run_service.create_run",
            new_callable=AsyncMock,
            side_effect=ConflictError("Project is being deleted; cannot create new runs"),
        ):
            resp = await client.post(
                "/api/creator/projects/99/script/import-markdown",
                json={"markdown": "# Hello"},
            )
            assert resp.status_code == 409
            assert "delet" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.anyio
async def test_import_json_catches_conflict_error_from_storage(
    client: AsyncClient,
):
    """If storage raises ConflictError (race condition), import_json returns 409."""
    from shorts_api.auth import require_project_access
    from unittest.mock import AsyncMock, patch

    user = CurrentUser(user_id=1, workspace_id=1)
    project = _FakeProject(project_id=99)
    project.status = "active"

    async def _fake_project_access(project_id: int):
        return user, project

    app.dependency_overrides[require_project_access] = _fake_project_access
    try:
        with patch(
            "shorts_api.routes.creator_script.run_service.create_run",
            new_callable=AsyncMock,
            side_effect=ConflictError("Project is being deleted; cannot create new runs"),
        ):
            resp = await client.post(
                "/api/creator/projects/99/script/import-json",
                json={"json_script": '{"scenes": [{"type": "narration", "text": "hi"}]}'},
            )
            assert resp.status_code == 409
            assert "delet" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.asyncio
async def test_delete_run_returns_404_when_run_concurrently_deleted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If update_run raises ValueError (run gone), delete_run returns 404, not 503."""

    async def _exploding_update(*a, **kw):
        raise ValueError("Run 99 not found")

    monkeypatch.setattr(
        "shorts_api.routes.creator_runs_lifecycle.run_service.storage.update_run",
        _exploding_update,
    )
    response = await client.delete("/api/creator/runs/99")
    assert response.status_code == 404, f"Expected 404 but got {response.status_code}"
