"""Pytest fixtures for API tests."""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from shorts_api.auth import CurrentUser, get_current_user
from shorts_api.main import app


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    """AsyncClient fixture for testing FastAPI app."""
    api_key = "test-api-key"
    expected_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    async def _fetch_one_stub(query: str, *args: object) -> dict[str, object] | None:
        if "FROM api_keys" in query:
            key_hash = args[0] if args else None
            if key_hash == expected_hash:
                return {"user_id": 1}
            return None
        if "FROM workspace_members" in query:
            user_id = args[0] if args else None
            if user_id == 1:
                return {"workspace_id": 1, "workspace_name": "workspace-1"}
            return None
        return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setattr("shorts_api.auth.fetch_one", _fetch_one_stub)

    # Mock the DB pool used by ApiKeyMiddleware to resolve API keys
    mock_connection = AsyncMock()
    mock_connection.fetchrow = AsyncMock(return_value={"user_id": 1})
    mock_connection.fetch = AsyncMock(return_value=[{"workspace_id": 1}])

    mock_pool = AsyncMock()
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_connection)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire = MagicMock(return_value=mock_cm)

    async def _get_pool_stub():
        return mock_pool

    monkeypatch.setattr("creator_service.db.get_pool", _get_pool_stub)

    async def _test_user_context() -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=1)

    app.dependency_overrides[get_current_user] = _test_user_context
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
