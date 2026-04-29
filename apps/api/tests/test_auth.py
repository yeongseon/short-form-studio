# pyright: reportMissingImports=false

"""Tests for API key authentication middleware."""

import pytest
from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from shorts_api.auth import ApiKeyMiddleware
from creator_service import db as db_module


def _make_app(api_key: str | None = None) -> FastAPI:
    """Create a minimal FastAPI app with the auth middleware."""
    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5174"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    test_app.add_middleware(ApiKeyMiddleware, api_key=api_key)

    @test_app.get("/health")
    async def health():
        return {"status": "ok"}

    @test_app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @test_app.get("/api/data")
    async def get_data():
        return {"data": "secret"}

    @test_app.get("/api/whoami")
    async def whoami(request: Request):
        user = getattr(request.state, "user", None)
        return {
            "user_id": getattr(user, "user_id", None),
            "workspace_id": getattr(user, "workspace_id", None),
        }

    @test_app.get("/docs")
    async def docs():
        return {"docs": True}

    @test_app.get("/openapi.json")
    async def openapi():
        return {"openapi": "3.0"}

    return test_app


@pytest.fixture
def api_key():
    return "test-secret-key-12345"


@pytest.fixture
async def authed_client(api_key, monkeypatch: pytest.MonkeyPatch):
    api_key_hash = __import__("hashlib").sha256(api_key.encode("utf-8")).hexdigest()

    async def fake_fetch_one(query: str, *args):
        if "FROM api_keys" in query:
            return {"user_id": 10} if args and args[0] == api_key_hash else None
        if "FROM workspace_members" in query:
            return {"workspace_id": 5}
        return None

    monkeypatch.setattr(db_module, "fetch_one", fake_fetch_one)
    app = _make_app(api_key=api_key)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def open_client(monkeypatch: pytest.MonkeyPatch):
    async def fake_fetch_one(_query: str, *_args):
        return None

    monkeypatch.setattr(db_module, "fetch_one", fake_fetch_one)
    app = _make_app(api_key=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_no_api_key_allows_health(open_client):
    response = await open_client.get("/health")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_no_api_key_allows_api_routes(open_client):
    response = await open_client.get("/api/data")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_health_requires_auth_when_api_key_set(authed_client):
    response = await authed_client.get("/health")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_healthz_always_public(authed_client):
    response = await authed_client.get("/healthz")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_docs_require_auth_when_api_key_set(authed_client):
    response = await authed_client.get("/docs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_openapi_requires_auth_when_api_key_set(authed_client):
    response = await authed_client.get("/openapi.json")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_docs_accessible_with_valid_api_key(authed_client, api_key):
    response = await authed_client.get("/docs", headers={"X-API-Key": api_key})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_accessible_with_valid_api_key(authed_client, api_key):
    response = await authed_client.get("/openapi.json", headers={"X-API-Key": api_key})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(authed_client):
    response = await authed_client.get("/api/data")
    assert response.status_code == 401
    body = response.json()
    assert body["detail"] == "Invalid or missing API key"


@pytest.mark.asyncio
async def test_wrong_api_key_returns_401(authed_client):
    response = await authed_client.get(
        "/api/data",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_correct_api_key_header(authed_client, api_key):
    response = await authed_client.get(
        "/api/data",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    assert response.json() == {"data": "secret"}


@pytest.mark.asyncio
async def test_query_param_api_key_rejected(authed_client, api_key):
    response = await authed_client.get(f"/api/data?api_key={api_key}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_empty_string_api_key_is_open_access():
    async def fake_fetch_one(_query: str, *_args):
        return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(db_module, "fetch_one", fake_fetch_one)
    app = _make_app(api_key="")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/data")
        assert response.status_code == 401
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_bearer_token_accepted(authed_client, api_key):
    response = await authed_client.get(
        "/api/data",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert response.json() == {"data": "secret"}


@pytest.mark.asyncio
async def test_bearer_wrong_token_rejected(authed_client):
    response = await authed_client.get(
        "/api/data",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bearer_malformed_rejected(authed_client):
    response = await authed_client.get(
        "/api/data",
        headers={"Authorization": "Token some-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_x_api_key_takes_precedence(authed_client, api_key):
    response = await authed_client.get(
        "/api/data",
        headers={"X-API-Key": api_key, "Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_identity_headers_do_not_set_authenticated_subject(authed_client, api_key):
    response = await authed_client.get(
        "/api/whoami",
        headers={"X-API-Key": api_key, "X-User-Id": "99", "X-Workspace-Id": "77"},
    )
    assert response.status_code == 200
    assert response.json() == {"user_id": 10, "workspace_id": 5}


@pytest.mark.asyncio
async def test_cors_preflight_bypasses_auth(authed_client):
    response = await authed_client.options(
        "/api/data",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5174"


@pytest.mark.asyncio
async def test_options_without_origin_requires_auth(authed_client):
    response = await authed_client.options("/api/data")
    assert response.status_code == 401
