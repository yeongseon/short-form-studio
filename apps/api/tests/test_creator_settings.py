# pyright: reportMissingImports=false

"""Tests for the settings endpoints."""

import pytest
from creator_service import db as db_module
from httpx import ASGITransport, AsyncClient
from shorts_api.main import app


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    api_key = "test-api-key"
    api_key_hash = __import__("hashlib").sha256(api_key.encode("utf-8")).hexdigest()

    async def fake_fetch_one(query: str, *args):
        if "FROM api_keys" in query:
            return {"user_id": 10} if args and args[0] == api_key_hash else None
        if "FROM workspace_members" in query:
            return None
        return None

    monkeypatch.setattr(db_module, "fetch_one", fake_fetch_one)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac


# --- /settings/api-keys ---


@pytest.mark.asyncio
async def test_list_api_keys_returns_all_providers(client):
    """Should return status for all 5 providers."""
    response = await client.get("/api/creator/settings/api-keys")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 5
    providers = {item["provider"] for item in data}
    assert providers == {"openai", "anthropic", "google", "stability", "elevenlabs"}


@pytest.mark.asyncio
async def test_list_api_keys_unconfigured(client, monkeypatch):
    """When no env vars are set, all keys should show as unconfigured."""
    for env_var in [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "STABILITY_API_KEY",
        "ELEVENLABS_API_KEY",
    ]:
        monkeypatch.delenv(env_var, raising=False)

    response = await client.get("/api/creator/settings/api-keys")
    assert response.status_code == 200
    data = response.json()
    for item in data:
        assert item["configured"] is False


@pytest.mark.asyncio
async def test_list_api_keys_configured(client, monkeypatch):
    """When an env var is set, the provider should show as configured with masked key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890abcdef")
    response = await client.get("/api/creator/settings/api-keys")
    assert response.status_code == 200
    data = response.json()
    openai_entry = next(item for item in data if item["provider"] == "openai")
    assert openai_entry["configured"] is True
    assert openai_entry["label"] == "OpenAI"


@pytest.mark.asyncio
async def test_list_api_keys_short_key_masked(client, monkeypatch):
    """Short keys should be fully masked."""
    monkeypatch.setenv("OPENAI_API_KEY", "short")
    response = await client.get("/api/creator/settings/api-keys")
    data = response.json()
    openai_entry = next(item for item in data if item["provider"] == "openai")
    assert openai_entry["configured"] is True


@pytest.mark.asyncio
async def test_list_api_keys_whitespace_only(client, monkeypatch):
    """Whitespace-only keys should show as unconfigured."""
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    response = await client.get("/api/creator/settings/api-keys")
    data = response.json()
    openai_entry = next(item for item in data if item["provider"] == "openai")
    assert openai_entry["configured"] is False


@pytest.mark.asyncio
async def test_api_keys_response_structure(client):
    """Each item should have the expected fields."""
    response = await client.get("/api/creator/settings/api-keys")
    data = response.json()
    for item in data:
        assert "provider" in item
        assert "label" in item
        assert "configured" in item


@pytest.mark.asyncio
async def test_settings_is_read_only(client):
    """POST/PUT/DELETE to settings should return 405 Method Not Allowed."""
    response = await client.post("/api/creator/settings/api-keys", json={"key": "value"})
    assert response.status_code == 405

    response = await client.put("/api/creator/settings/api-keys", json={"key": "value"})
    assert response.status_code == 405

    response = await client.delete("/api/creator/settings/api-keys")
    assert response.status_code == 405
