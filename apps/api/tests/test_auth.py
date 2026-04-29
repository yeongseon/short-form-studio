# pyright: reportMissingImports=false

"""Tests for API key authentication middleware."""

import pytest
from creator_domain.models import User
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient
from shorts_api.auth import ApiKeyMiddleware, get_current_user
from starlette.requests import Request


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
async def authed_client(api_key):
    """Client for an app with API_KEY configured."""
    app = _make_app(api_key=api_key)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def open_client():
    """Client for an app with no API_KEY (open access)."""
    app = _make_app(api_key=None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --- Tests with no API key (open access mode) ---


@pytest.mark.asyncio
async def test_no_api_key_allows_health(open_client):
    """When API_KEY is not set, health should be accessible."""
    response = await open_client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_no_api_key_allows_api_routes(open_client):
    """API routes should work without auth when API_KEY is unset."""
    response = await open_client.get("/api/data")
    assert response.status_code == 200


# --- Tests with API key configured ---


@pytest.mark.asyncio
async def test_health_requires_auth_when_api_key_set(authed_client):
    """Detailed /health endpoint requires auth when API_KEY is set."""
    response = await authed_client.get("/health")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_healthz_always_public(authed_client):
    """Liveness probe /healthz should be accessible without auth even when API_KEY is set."""
    response = await authed_client.get("/healthz")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_docs_require_auth_when_api_key_set(authed_client):
    """Docs endpoints should require auth when API_KEY is configured."""
    response = await authed_client.get("/docs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_openapi_requires_auth_when_api_key_set(authed_client):
    """OpenAPI JSON should require auth when API_KEY is configured."""
    response = await authed_client.get("/openapi.json")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_docs_accessible_with_valid_api_key(authed_client, api_key):
    """Docs endpoints should be accessible with a valid API key."""
    response = await authed_client.get("/docs", headers={"X-API-Key": api_key})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_accessible_with_valid_api_key(authed_client, api_key):
    """OpenAPI JSON should be accessible with a valid API key."""
    response = await authed_client.get("/openapi.json", headers={"X-API-Key": api_key})
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_missing_api_key_returns_401(authed_client):
    """Requests without API key should get 401."""
    response = await authed_client.get("/api/data")
    assert response.status_code == 401
    body = response.json()
    assert body["detail"] == "Invalid or missing API key"


@pytest.mark.asyncio
async def test_wrong_api_key_returns_401(authed_client):
    """Requests with wrong API key should get 401."""
    response = await authed_client.get(
        "/api/data",
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_correct_api_key_header(authed_client, api_key):
    """Requests with correct X-API-Key header should succeed."""
    response = await authed_client.get(
        "/api/data",
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200
    assert response.json() == {"data": "secret"}


@pytest.mark.asyncio
async def test_query_param_api_key_rejected(authed_client, api_key):
    """API keys via query params should be rejected to prevent log leakage."""
    response = await authed_client.get(f"/api/data?api_key={api_key}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_empty_string_api_key_is_open_access():
    """An empty string API_KEY should be treated as no auth (open access)."""
    app = _make_app(api_key="")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/data")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_bearer_token_accepted(authed_client, api_key):
    """Authorization: Bearer <key> should be accepted as valid auth."""
    response = await authed_client.get(
        "/api/data",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert response.json() == {"data": "secret"}


@pytest.mark.asyncio
async def test_bearer_wrong_token_rejected(authed_client):
    """Authorization: Bearer with wrong key should get 401."""
    response = await authed_client.get(
        "/api/data",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bearer_malformed_rejected(authed_client):
    """Malformed Authorization header (no Bearer prefix) should get 401."""
    response = await authed_client.get(
        "/api/data",
        headers={"Authorization": "Token some-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_x_api_key_takes_precedence(authed_client, api_key):
    """When both X-API-Key and Bearer are present, X-API-Key takes precedence."""
    response = await authed_client.get(
        "/api/data",
        headers={"X-API-Key": api_key, "Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_cors_preflight_bypasses_auth(authed_client):
    """CORS preflight (OPTIONS with Origin) should bypass auth even when API_KEY is set."""
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
    """OPTIONS without Origin header is not CORS preflight — should require auth."""
    response = await authed_client.options("/api/data")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_current_user_without_api_key_returns_401():
    scope = {"type": "http", "headers": []}
    request = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "API key required"


@pytest.mark.asyncio
async def test_get_current_user_with_invalid_api_key_returns_401(monkeypatch):
    async def _no_user(_provider: str, _subject: str):
        return None

    monkeypatch.setattr("shorts_api.auth.user_service.get_user_by_auth", _no_user)
    scope = {"type": "http", "headers": [(b"x-api-key", b"invalid-key")]}
    request = Request(scope)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(request)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid API key"


@pytest.mark.asyncio
async def test_get_current_user_with_valid_api_key_resolves_user(monkeypatch):
    key = "valid-key"
    expected_subject = "cc358b85b8b7"

    async def _user_for_auth(provider: str, subject: str):
        assert provider == "api_key"
        assert subject == expected_subject
        return User(
            id=123,
            email="test@example.com",
            name="Test User",
            workspace_id=10,
            auth_provider="api_key",
            auth_subject=subject,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("shorts_api.auth.user_service.get_user_by_auth", _user_for_auth)
    scope = {"type": "http", "headers": [(b"x-api-key", key.encode())]}
    request = Request(scope)

    result = await get_current_user(request)

    assert result.id == 123
    assert result.auth_provider == "api_key"
    assert result.auth_subject == expected_subject
