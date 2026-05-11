"""Tests for /api/creator/workspaces routes."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from shorts_api.routes import creator_workspaces


@pytest.fixture
def mock_pool(monkeypatch):
    """Mock get_pool in the workspaces route module."""
    mock_connection = AsyncMock()
    mock_connection.fetch = AsyncMock(return_value=[])

    pool = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=mock_cm)

    async def _get_pool():
        return pool

    monkeypatch.setattr(creator_workspaces, "get_pool", _get_pool)
    return mock_connection


@pytest.mark.anyio
async def test_list_workspaces_returns_workspaces(client, mock_pool):
    """GET /api/creator/workspaces returns workspace list."""
    resp = await client.get("/api/creator/workspaces")
    assert resp.status_code == 200
    data = resp.json()
    assert "workspaces" in data
    assert isinstance(data["workspaces"], list)


@pytest.mark.anyio
async def test_list_workspaces_with_data(client, mock_pool):
    """GET /api/creator/workspaces returns workspace data from DB."""
    mock_pool.fetch = AsyncMock(
        side_effect=[
            [{"workspace_id": 1}, {"workspace_id": 2}],
            [{"id": 1, "name": "My Workspace"}, {"id": 2, "name": "Team Workspace"}],
        ]
    )

    resp = await client.get("/api/creator/workspaces")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["workspaces"]) == 2
    assert data["workspaces"][0]["name"] == "My Workspace"
    assert data["workspaces"][1]["name"] == "Team Workspace"


@pytest.mark.anyio
async def test_list_workspaces_empty(client, mock_pool):
    """GET /api/creator/workspaces returns empty list when no memberships."""
    mock_pool.fetch = AsyncMock(return_value=[])

    resp = await client.get("/api/creator/workspaces")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workspaces"] == []


@pytest.mark.anyio
async def test_list_workspaces_unauthenticated():
    """GET /api/creator/workspaces without API key returns 401."""
    from httpx import ASGITransport, AsyncClient
    from shorts_api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/creator/workspaces")
        assert resp.status_code == 401
