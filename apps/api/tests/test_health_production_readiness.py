import importlib
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient


def _set_production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://svc_user:strong-pass@db.internal:5432/shorts")
    monkeypatch.setenv("CORS_ORIGINS", "https://studio.example.com")
    monkeypatch.setenv("REDIS_URL", "redis://redis.internal:6379/0")


def _main_module():
    return importlib.import_module("shorts_api.main")


@pytest.mark.asyncio
async def test_health_returns_200_when_db_and_redis_are_healthy(monkeypatch: pytest.MonkeyPatch):
    _set_production_env(monkeypatch)
    main_module = _main_module()

    fake_pool = Mock()
    fake_pool.fetchval = AsyncMock(return_value=1)

    fake_redis = Mock()
    fake_redis.ping = AsyncMock(return_value=True)
    fake_redis.aclose = AsyncMock(return_value=None)

    with (
        patch.object(main_module, "get_pool", AsyncMock(return_value=fake_pool)),
        patch.object(main_module.Redis, "from_url", return_value=fake_redis),
    ):
        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["checks"]["database"]["status"] == "ok"
    assert response.json()["checks"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_returns_503_when_database_is_down(monkeypatch: pytest.MonkeyPatch):
    _set_production_env(monkeypatch)
    main_module = _main_module()

    fake_redis = Mock()
    fake_redis.ping = AsyncMock(return_value=True)
    fake_redis.aclose = AsyncMock(return_value=None)

    with (
        patch.object(
            main_module, "get_pool", AsyncMock(side_effect=RuntimeError("db unavailable"))
        ),
        patch.object(main_module.Redis, "from_url", return_value=fake_redis),
    ):
        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["checks"]["database"]["status"] == "down"
    assert detail["checks"]["redis"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_returns_503_when_redis_is_down(monkeypatch: pytest.MonkeyPatch):
    _set_production_env(monkeypatch)
    main_module = _main_module()

    fake_pool = Mock()
    fake_pool.fetchval = AsyncMock(return_value=1)

    fake_redis = Mock()
    fake_redis.ping = AsyncMock(side_effect=RuntimeError("redis unavailable"))
    fake_redis.aclose = AsyncMock(return_value=None)

    with (
        patch.object(main_module, "get_pool", AsyncMock(return_value=fake_pool)),
        patch.object(main_module.Redis, "from_url", return_value=fake_redis),
    ):
        transport = ASGITransport(app=main_module.app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["checks"]["database"]["status"] == "ok"
    assert detail["checks"]["redis"]["status"] == "down"
