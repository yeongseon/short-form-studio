"""Pytest fixtures for API tests."""

import hashlib

import pytest
from httpx import ASGITransport, AsyncClient
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

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac
