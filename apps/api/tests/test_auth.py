# pyright: reportMissingImports=false

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
import pytest
from shorts_api.auth import ApiKeyMiddleware, get_current_user, require_workspace_access
from starlette.requests import Request


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ApiKeyMiddleware)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/api/data")
    async def get_data():
        return {"data": "secret"}

    return app


@pytest.fixture
async def client():
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_healthz_public(client):
    response = await client.get("/healthz")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_middleware_pass_through_for_non_public_routes(client):
    response = await client.get("/api/data")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_cors_preflight_bypasses_auth(client):
    response = await client.options(
        "/api/data",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in (200, 204)


@pytest.mark.asyncio
async def test_get_current_user_without_api_key_returns_401():
    request = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "API key required"


@pytest.mark.asyncio
async def test_get_current_user_with_invalid_api_key_returns_401(monkeypatch):
    async def _fetch_one(*_args, **_kwargs):
        return None

    monkeypatch.setattr("shorts_api.auth.fetch_one", _fetch_one)
    request = Request({"type": "http", "headers": [(b"x-api-key", b"invalid-key")]})
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid API key"


@pytest.mark.asyncio
async def test_get_current_user_resolves_from_api_keys_and_membership(monkeypatch):
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def _fetch_one(query: str, *args):
        calls.append((query, args))
        if "FROM api_keys" in query:
            return {"user_id": 123}
        if "FROM workspace_members" in query:
            return {"workspace_id": 10}
        return None

    monkeypatch.setattr("shorts_api.auth.fetch_one", _fetch_one)
    request = Request({"type": "http", "headers": [(b"x-api-key", b"valid-key")]})
    result = await get_current_user(request)

    assert result["user_id"] == 123
    assert result["workspace_id"] == 10
    assert result["auth_provider"] == "api_key"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_get_current_user_handles_missing_workspace_membership(monkeypatch):
    async def _fetch_one(query: str, *args):
        if "FROM api_keys" in query:
            return {"user_id": 123}
        if "FROM workspace_members" in query:
            return None
        return None

    monkeypatch.setattr("shorts_api.auth.fetch_one", _fetch_one)
    request = Request({"type": "http", "headers": [(b"x-api-key", b"valid-key")]})
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "No workspace membership"


@pytest.mark.asyncio
async def test_require_workspace_access_denies_without_membership(monkeypatch):
    async def _no_access(_workspace_id: int, _user_id: int) -> bool:
        return False

    monkeypatch.setattr("shorts_api.auth.workspace_service.check_access", _no_access)
    user = {
        "user_id": 1,
        "auth_provider": "api_key",
        "auth_subject": "subject",
        "workspace_id": None,
    }

    with pytest.raises(HTTPException) as exc_info:
        await require_workspace_access(99, user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_workspace_access_allows_with_membership(monkeypatch):
    async def _has_access(_workspace_id: int, _user_id: int) -> bool:
        return True

    monkeypatch.setattr("shorts_api.auth.workspace_service.check_access", _has_access)
    user = {
        "user_id": 2,
        "auth_provider": "api_key",
        "auth_subject": "subject",
        "workspace_id": 10,
    }

    result = await require_workspace_access(100, user)
    assert result["user_id"] == 2
