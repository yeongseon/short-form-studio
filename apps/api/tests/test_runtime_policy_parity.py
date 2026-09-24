import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, Mock, patch
from starlette.requests import Request

from shorts_api.app_factory import create_app
from shorts_api.lifecycle import shutdown_state
from shorts_api.routes.admin import require_admin
from shorts_api import health as health_module


@pytest.mark.asyncio
@pytest.mark.parametrize("pytest_marker", [False, True])
async def test_short_production_admin_key_rejected_with_or_without_pytest_marker(
    monkeypatch: pytest.MonkeyPatch, pytest_marker: bool,
) -> None:
    # Given a short matching key in production, with either test marker state.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ADMIN_API_KEY", "short")
    if pytest_marker:
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "synthetic marker")
    else:
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # When authenticating at the runtime admin boundary.
    with pytest.raises(HTTPException) as error:
        await require_admin("short")
    # Then the request fails closed regardless of how it was launched.
    assert error.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("pytest_marker", [False, True])
async def test_shutdown_guard_rejects_unprotected_requests_with_or_without_pytest_marker(
    monkeypatch: pytest.MonkeyPatch, pytest_marker: bool,
) -> None:
    # Given the server draining, regardless of the pytest marker.
    monkeypatch.setenv("ENVIRONMENT", "development")
    if pytest_marker:
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "synthetic marker")
    else:
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    app = create_app()
    monkeypatch.setattr(shutdown_state, "is_shutting_down", True)
    # When querying an unprotected endpoint subject to the shutdown guard.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/docs")
    # Then the guard treats both requests identically.
    assert response.status_code == 503
    assert response.json() == {"detail": "Server shutting down"}


@pytest.mark.asyncio
@pytest.mark.parametrize("pytest_marker", [False, True])
async def test_production_health_stays_unavailable_during_shutdown_under_either_marker(
    monkeypatch: pytest.MonkeyPatch, pytest_marker: bool,
) -> None:
    # Given healthy dependencies but an active shutdown in production.
    monkeypatch.setenv("ENVIRONMENT", "production")
    if pytest_marker:
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "synthetic marker")
    else:
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    pool = Mock(fetchval=AsyncMock(return_value=1))
    redis = Mock(ping=AsyncMock(return_value=True), aclose=AsyncMock(return_value=None))
    monkeypatch.setattr(shutdown_state, "is_shutting_down", True)
    with (
        patch.object(health_module, "_resolve_get_pool", return_value=AsyncMock(return_value=pool)),
        patch.object(health_module, "_resolve_redis_from_url", return_value=lambda _: redis),
    ):
        # When reading the production health endpoint.
        with pytest.raises(HTTPException) as error:
            await health_module.health(Request({"type": "http", "headers": []}))
    # Then neither marker state can conceal shutdown readiness.
    assert error.value.status_code == 503
    assert error.value.detail["status"] == "unavailable"
