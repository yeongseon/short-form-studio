from __future__ import annotations

import pytest
from unittest.mock import MagicMock


def _mock_authz(monkeypatch):
    """Mock authorization services to allow access for run_id=1,2,9 in workspace_id=1."""
    mock_run = MagicMock()
    mock_run.project_id = 1

    mock_project = MagicMock()
    mock_project.workspace_id = 1

    allowed_runs = {1, 2, 9}

    async def mock_get_run(run_id, workspace_id):
        if run_id in allowed_runs and workspace_id == 1:
            mock_run.id = run_id
            return mock_run
        return None

    async def mock_get_project(project_id, workspace_id):
        if workspace_id == 1:
            return mock_project
        return None

    async def mock_check_access(workspace_id, user_id):
        return workspace_id == 1 and user_id == 1

    monkeypatch.setattr("creator_service.run_service.run_service.get_run", mock_get_run)
    monkeypatch.setattr("creator_service.project_service.project_service.get_project", mock_get_project)
    monkeypatch.setattr("creator_service.workspace_service.workspace_service.check_access", mock_check_access)


@pytest.mark.asyncio
async def test_artifact_file_serving_reads_from_storage_backend(client, monkeypatch):
    payload = b"binary-artifact-content"

    def _read_artifact_bytes(path: str) -> bytes:
        assert path == "1/render/output.mp4"
        return payload

    _mock_authz(monkeypatch)
    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", _read_artifact_bytes)

    response = await client.get("/api/artifacts/files/1/render/output.mp4")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("video/mp4")


@pytest.mark.asyncio
async def test_artifact_file_serving_returns_404_when_storage_misses(client, monkeypatch):
    def _read_artifact_bytes(_path: str) -> bytes:
        raise FileNotFoundError

    _mock_authz(monkeypatch)
    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", _read_artifact_bytes)

    response = await client.get("/api/artifacts/files/1/render/missing.bin")

    assert response.status_code == 404
    assert response.json() == {"detail": "Artifact not found"}


@pytest.mark.asyncio
async def test_artifact_file_serving_returns_404_for_non_numeric_run_id(client, monkeypatch):
    """Non-numeric run_id prefix must be rejected with 404 (no authz bypass)."""
    response = await client.get("/api/artifacts/files/run-1/render/output.mp4")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_legacy_artifact_route_reads_from_storage_backend(client, monkeypatch):
    payload = b"legacy-route-content"

    def _read_artifact_bytes(path: str) -> bytes:
        assert path == "2/render/final.png"
        return payload

    _mock_authz(monkeypatch)
    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", _read_artifact_bytes)

    response = await client.get("/artifacts/2/render/final.png")

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("image/png")
    assert "deprecated" in response.headers["warning"].lower()


@pytest.mark.asyncio
async def test_legacy_artifact_route_returns_404_for_non_numeric_run_id(client, monkeypatch):
    """Non-numeric run_id prefix must be rejected with 404 on deprecated route too."""
    response = await client.get("/artifacts/run-2/render/final.png")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_artifact_file_serving_returns_500_when_storage_fails(client, monkeypatch):
    def _read_artifact_bytes(_path: str) -> bytes:
        raise RuntimeError("storage backend unavailable")

    _mock_authz(monkeypatch)
    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", _read_artifact_bytes)

    response = await client.get("/api/artifacts/files/9/render/output.mp4")

    assert response.status_code == 500
    assert response.json() == {"detail": "Artifact read failed"}
