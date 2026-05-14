# pyright: reportMissingImports=false

"""Tests for X-Workspace-Id header support in multi-workspace auth."""

import hashlib

import pytest
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncClient
from shorts_api.auth import ApiKeyMiddleware, CurrentUser


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with the auth middleware."""
    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.add_middleware(ApiKeyMiddleware)

    @test_app.get("/api/creator/test")
    async def test_endpoint(request: Request):
        user = request.state.user
        return {"status": "ok", "workspace_id": user.workspace_id}

    return test_app


@pytest.fixture
def api_key():
    return "test-multi-workspace-key"


@pytest.fixture
async def multi_workspace_client(api_key, monkeypatch: pytest.MonkeyPatch):
    """Client for an app with multiple workspace memberships."""
    expected_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    class _Conn:
        async def fetchrow(self, _query: str, key_hash: str):
            if key_hash == expected_hash:
                return {"user_id": 1}
            return None

        async def fetch(self, _query: str, user_id: int):
            # Return multiple workspaces for the user
            if user_id == 1:
                return [
                    {"workspace_id": 10},
                    {"workspace_id": 20},
                    {"workspace_id": 30},
                ]
            return []

    class _Acquire:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, exc_type, exc, tb):
            _ = (exc_type, exc, tb)
            return False

    class _Pool:
        def acquire(self):
            return _Acquire()

    async def _get_pool(self):  # Accept self parameter
        return _Pool()

    monkeypatch.setattr(
        "shorts_api.auth.ApiKeyMiddleware._get_pool",
        _get_pool,
    )

    app = _make_app()
    return AsyncClient(app=app, base_url="http://test"), api_key


@pytest.mark.asyncio
async def test_x_workspace_id_selects_correct_workspace(multi_workspace_client):
    """Test that X-Workspace-Id header selects the specified workspace."""
    client, api_key = multi_workspace_client
    
    response = await client.get(
        "/api/creator/test",
        headers={
            "X-API-Key": api_key,
            "X-Workspace-Id": "20",
        },
    )
    
    assert response.status_code == 200
    assert response.json()["workspace_id"] == 20


@pytest.mark.asyncio
async def test_x_workspace_id_non_member_workspace_returns_404(multi_workspace_client):
    """Test that X-Workspace-Id with non-member workspace returns 404."""
    client, api_key = multi_workspace_client
    
    # User only has workspaces 10, 20, 30, not 999
    response = await client.get(
        "/api/creator/test",
        headers={
            "X-API-Key": api_key,
            "X-Workspace-Id": "999",
        },
    )
    
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_x_workspace_id_falls_back_to_first_workspace(multi_workspace_client):
    """Test that missing X-Workspace-Id falls back to first workspace."""
    client, api_key = multi_workspace_client
    
    response = await client.get(
        "/api/creator/test",
        headers={
            "X-API-Key": api_key,
        },
    )
    
    assert response.status_code == 200
    assert response.json()["workspace_id"] == 10


@pytest.mark.asyncio
async def test_invalid_x_workspace_id_returns_404(multi_workspace_client):
    """Test that invalid (non-numeric) X-Workspace-Id is rejected."""
    client, api_key = multi_workspace_client
    
    response = await client.get(
        "/api/creator/test",
        headers={
            "X-API-Key": api_key,
            "X-Workspace-Id": "not-a-number",
        },
    )
    
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_bearer_token_with_workspace_id_header(multi_workspace_client):
    """Test that bearer token auth works with X-Workspace-Id header."""
    client, api_key = multi_workspace_client
    
    response = await client.get(
        "/api/creator/test",
        headers={
            "Authorization": f"Bearer {api_key}",
            "X-Workspace-Id": "20",
        },
    )
    
    assert response.status_code == 200
    assert response.json()["workspace_id"] == 20
