"""Tests for /api/creator/users routes."""

import pytest


@pytest.mark.anyio
async def test_get_me_returns_user_identity(client):
    """GET /api/creator/users/me returns authenticated user info."""
    resp = await client.get("/api/creator/users/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == 1
    assert data["workspace_id"] == 1


@pytest.mark.anyio
async def test_get_me_unauthenticated():
    """GET /api/creator/users/me without API key returns 401."""
    from httpx import ASGITransport, AsyncClient
    from shorts_api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/creator/users/me")
        assert resp.status_code == 401
