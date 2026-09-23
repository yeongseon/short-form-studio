from unittest.mock import AsyncMock

import pytest
from creator_service.admin_service import admin_service
from httpx import ASGITransport, AsyncClient
from shorts_api.app_factory import create_app


@pytest.mark.parametrize("component", ["db", "redis", "redis_close"])
async def test_admin_health_emits_stable_category_for_backend_failure(monkeypatch: pytest.MonkeyPatch, component: str, caplog: pytest.LogCaptureFixture) -> None:
    # Given: actual health service, only the failed backend seam is replaced.
    monkeypatch.setenv("ADMIN_API_KEY", "synthetic-admin-key-701")
    failure = RuntimeError("postgresql://synthetic:private-password@db.invalid/studio gsk_syntheticPrivate /home/synthetic/private")
    redis_client = AsyncMock()
    if component == "redis":
        redis_client.ping.side_effect = failure
    if component == "redis_close":
        redis_client.aclose.side_effect = failure
    monkeypatch.setattr(admin_service, "_redis_client", lambda: redis_client)
    pool = AsyncMock()
    pool.acquire = lambda: pool
    pool.__aenter__.return_value = pool
    monkeypatch.setattr("creator_service.admin_service.get_pool", AsyncMock(
        side_effect=failure if component == "db" else None, return_value=pool,
    ))
    # When
    async with AsyncClient(transport=ASGITransport(app=create_app(), raise_app_exceptions=False), base_url="http://test") as client:
        response = await client.get("/api/admin/health", headers={"X-Admin-Key": "synthetic-admin-key-701"})
    # Then
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db" if component == "db" else "redis"] == {"ok": False, "error": "UNAVAILABLE"}
    assert body["redis" if component == "db" else "db"] == {"ok": True}
    redis_client.aclose.assert_awaited_once()
    assert "private-password" not in caplog.text


@pytest.mark.parametrize("headers, status", [
    ({}, 401), ({"X-API-Key": "personal-one"}, 401),
    ({"X-Admin-Key": "incorrect"}, 403),
])
async def test_admin_health_requires_admin_credentials(monkeypatch: pytest.MonkeyPatch, headers: dict[str, str], status: int) -> None:
    # Given: preserve the existing separate admin auth contract.
    monkeypatch.setenv("ADMIN_API_KEY", "synthetic-admin-key-701")
    backend = AsyncMock(side_effect=AssertionError("unauthorized health backend access"))
    monkeypatch.setattr("creator_service.admin_service.get_pool", backend)
    # When
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        response = await client.get("/api/admin/health", headers=headers)
    # Then
    assert response.status_code == status
    backend.assert_not_awaited()
