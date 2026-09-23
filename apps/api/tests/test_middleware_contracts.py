"""Characterization of the factory contracts surrounding #815."""

import logging

import anyio
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from shorts_api.app_factory import create_app
from shorts_api.auth import _current_user_ctx
from shorts_api.lifecycle import shutdown_state
from starlette.exceptions import HTTPException

from tests.auth_lookup_support import AuthDatabase, auth_db  # noqa: F401
from tests.middleware_app_support import (
    ORIGIN, SECURITY_HEADERS, middleware_app, middleware_client,  # noqa: F401
)


@pytest.mark.parametrize("origin", [ORIGIN, "https://foreign.example.test"])
@pytest.mark.parametrize("method", ["POST", "NOT_ALLOWED"])
async def test_cors_preflight_precedes_auth_and_shutdown(
    middleware_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, origin: str, method: str,
) -> None:
    # Given: a draining server and no credentials; CORS owns preflight responses.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(shutdown_state, "is_shutting_down", True)
    middleware_client.headers.clear()
    # When
    response = await middleware_client.options("/api/creator/projects", headers={
        "Origin": origin, "Access-Control-Request-Method": method,
        "Access-Control-Request-Headers": "x-api-key,content-type",
    })
    # Then
    assert response.status_code == (200 if origin == ORIGIN and method == "POST" else 400)
    assert response.headers.get("access-control-allow-origin") == (ORIGIN if origin == ORIGIN else None)
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "Origin" in response.headers["vary"]
    assert shutdown_state.inflight_requests == 0


@pytest.mark.parametrize("path,status", [("/api/creator/projects", 503), ("/healthz", 200)])
async def test_shutdown_guard_preserves_health_exception(
    middleware_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, path: str, status: int,
) -> None:
    # Given
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(shutdown_state, "is_shutting_down", True)
    # When
    response = await middleware_client.get(path)
    # Then
    assert response.status_code == status
    if status == 503:
        assert response.json() == {"detail": "Server shutting down"}
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert shutdown_state.inflight_requests == 0
    assert _current_user_ctx.get() is None


async def test_shutdown_keeps_auth_rejection_precedence(
    middleware_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: retain the existing auth-before-shutdown contract.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(shutdown_state, "is_shutting_down", True)
    middleware_client.headers.clear()
    # When
    response = await middleware_client.get("/api/creator/projects")
    # Then
    assert response.status_code == 401
    assert response.json() == {"detail": "API key required"}


async def test_pytest_marker_does_not_bypass_shutdown_guard(
    middleware_client: AsyncClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the test marker is set and the server is draining.
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "synthetic marker")
    monkeypatch.setattr(shutdown_state, "is_shutting_down", True)
    # When
    response = await middleware_client.get("/api/creator/projects")
    # Then
    assert response.status_code == 503
    assert response.json() == {"detail": "Server shutting down"}


@pytest.mark.parametrize("environment", ["development", "staging", "production"])
async def test_header_environment_policy_is_preserved(
    monkeypatch: pytest.MonkeyPatch, environment: str,
) -> None:
    # Given
    monkeypatch.setenv("ENVIRONMENT", environment)
    # When
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/healthz")
    # Then
    assert response.status_code == 200
    for name, value in SECURITY_HEADERS.items():
        assert response.headers.get(name) == (value if environment == "production" else None)


@pytest.mark.parametrize("status", [401, 409, 204, 304])
async def test_http_exception_handler_preserves_status_and_headers(
    middleware_app: FastAPI, middleware_client: AsyncClient, status: int,
) -> None:
    # Given: exercise #701's actual handler, including bodyless statuses.
    async def reject() -> None:
        raise HTTPException(status, detail="Bearer synthetic-handler-secret", headers={
            "WWW-Authenticate": "Bearer", "Retry-After": "17", "ETag": '"version-1"',
        })

    middleware_app.add_api_route("/handler-contract", reject)
    # When
    response = await middleware_client.get("/handler-contract")
    # Then
    assert response.status_code == status
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["retry-after"] == "17"
    assert response.headers["etag"] == '"version-1"'
    assert "synthetic-handler-secret" not in response.text
    if status in (204, 304):
        assert response.content == b""


async def test_concurrent_requests_keep_identity_and_cleanup(
    middleware_client: AsyncClient, caplog: pytest.LogCaptureFixture,
) -> None:
    # Given: SQL-backed keys for distinct users, concurrent HTTP requests.
    caplog.set_level(logging.INFO, logger="shorts_api.app_factory")

    async def request(key: str) -> None:
        response = await middleware_client.get("/api/creator/projects", headers={"X-API-Key": key})
        assert response.status_code == 200
        assert _current_user_ctx.get() is None

    # When
    async with anyio.create_task_group() as group:
        group.start_soon(request, "personal-one")
        group.start_soon(request, "other-user")
    # Then
    records = [r for r in caplog.records if r.name == "shorts_api.app_factory"]
    assert sorted((r.user_id, r.key_id, r.workspace_id) for r in records) == [(7, 71, 10), (8, 81, 30)]
    assert shutdown_state.inflight_requests == 0
    assert _current_user_ctx.get() is None
