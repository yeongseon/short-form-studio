"""Tests for artifact endpoint authorization (IDOR protection)."""

import pytest
from unittest.mock import MagicMock
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_artifact_endpoint_authorized_access(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that artifact endpoint works for authorized user."""
    # Mock run and project objects
    mock_run = MagicMock()
    mock_run.id = 1
    mock_run.project_id = 1
    
    mock_project = MagicMock()
    mock_project.id = 1
    mock_project.workspace_id = 1
    
    async def mock_get_run(run_id, workspace_id):
        if run_id == 1 and workspace_id == 1:
            return mock_run
        return None
    
    async def mock_get_project(project_id, workspace_id):
        if project_id == 1 and workspace_id == 1:
            return mock_project
        return None
    
    async def mock_check_access(workspace_id, user_id):
        return workspace_id == 1 and user_id == 1
    
    def mock_read_artifact(key):
        return b"test content"
    
    monkeypatch.setattr("creator_service.run_service.run_service.get_run", mock_get_run)
    monkeypatch.setattr("creator_service.project_service.project_service.get_project", mock_get_project)
    monkeypatch.setattr("creator_service.workspace_service.workspace_service.check_access", mock_check_access)
    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", mock_read_artifact)
    
    # Request should succeed
    response = await client.get("/api/artifacts/files/1/render/output.mp4")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_artifact_endpoint_unauthorized_access_idor(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that artifact endpoint returns 404 for unauthorized run (IDOR protection)."""
    # Mock run lookup to return None (simulating run not in user's workspace)
    async def mock_get_run(run_id, workspace_id):
        return None  # Run not found in this workspace
    
    monkeypatch.setattr("creator_service.run_service.run_service.get_run", mock_get_run)
    
    # Request should fail with 404 (anti-enumeration: never reveal if run exists in another workspace)
    response = await client.get("/api/artifacts/files/999/render/output.mp4")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_artifact_endpoint_project_not_found(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that artifact endpoint returns 404 when project is not found."""
    mock_run = MagicMock()
    mock_run.id = 1
    mock_run.project_id = 1
    
    async def mock_get_run(run_id, workspace_id):
        if run_id == 1 and workspace_id == 1:
            return mock_run
        return None
    
    async def mock_get_project(project_id, workspace_id):
        return None  # Project not found
    
    monkeypatch.setattr("creator_service.run_service.run_service.get_run", mock_get_run)
    monkeypatch.setattr("creator_service.project_service.project_service.get_project", mock_get_project)
    
    # Request should fail with 404
    response = await client.get("/api/artifacts/files/1/render/output.mp4")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_artifact_endpoint_workspace_access_denied(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that artifact endpoint returns 404 when workspace access is denied."""
    mock_run = MagicMock()
    mock_run.id = 1
    mock_run.project_id = 1
    
    mock_project = MagicMock()
    mock_project.id = 1
    mock_project.workspace_id = 2  # Different workspace
    
    async def mock_get_run(run_id, workspace_id):
        if run_id == 1 and workspace_id == 1:
            return mock_run
        return None
    
    async def mock_get_project(project_id, workspace_id):
        if project_id == 1 and workspace_id == 1:
            return mock_project
        return None
    
    async def mock_check_access(workspace_id, user_id):
        return False  # User does not have access to workspace 2
    
    monkeypatch.setattr("creator_service.run_service.run_service.get_run", mock_get_run)
    monkeypatch.setattr("creator_service.project_service.project_service.get_project", mock_get_project)
    monkeypatch.setattr("creator_service.workspace_service.workspace_service.check_access", mock_check_access)
    
    # Request should fail with 404
    response = await client.get("/api/artifacts/files/1/render/output.mp4")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_deprecated_artifact_endpoint_authorized(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that deprecated artifact endpoint works for authorized user."""
    mock_run = MagicMock()
    mock_run.id = 1
    mock_run.project_id = 1
    
    mock_project = MagicMock()
    mock_project.id = 1
    mock_project.workspace_id = 1
    
    async def mock_get_run(run_id, workspace_id):
        if run_id == 1 and workspace_id == 1:
            return mock_run
        return None
    
    async def mock_get_project(project_id, workspace_id):
        if project_id == 1 and workspace_id == 1:
            return mock_project
        return None
    
    async def mock_check_access(workspace_id, user_id):
        return workspace_id == 1 and user_id == 1
    
    def mock_read_artifact(key):
        return b"test content"
    
    monkeypatch.setattr("creator_service.run_service.run_service.get_run", mock_get_run)
    monkeypatch.setattr("creator_service.project_service.project_service.get_project", mock_get_project)
    monkeypatch.setattr("creator_service.workspace_service.workspace_service.check_access", mock_check_access)
    monkeypatch.setattr("shorts_api.main.read_artifact_bytes", mock_read_artifact)
    
    response = await client.get("/artifacts/1/audio/audio.wav")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


@pytest.mark.asyncio
async def test_deprecated_artifact_endpoint_unauthorized_idor(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that deprecated artifact endpoint returns 404 for unauthorized run (IDOR protection)."""
    async def mock_get_run(run_id, workspace_id):
        return None  # Run not found in this workspace
    
    monkeypatch.setattr("creator_service.run_service.run_service.get_run", mock_get_run)
    
    response = await client.get("/artifacts/999/audio/audio.wav")
    assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
