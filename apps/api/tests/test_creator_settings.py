# pyright: reportMissingImports=false

"""Tests for the settings endpoints."""

import hashlib

import pytest
from httpx import ASGITransport, AsyncClient
from shorts_api.main import app


@pytest.fixture
async def settings_client(monkeypatch: pytest.MonkeyPatch):
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
    app.state.shutdown_requested = False

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
    """Should return status for all 6 approved providers (incl. groq for STT)."""
    response = await client.get("/api/creator/settings/api-keys")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 6
    providers = {item["provider"] for item in data}
    assert providers == {"openai", "anthropic", "google", "stability", "elevenlabs", "groq"}


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
    """When an env var is set, the provider should show as configured (presence only, no value)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-1234567890abcdef")
    response = await client.get("/api/creator/settings/api-keys")
    assert response.status_code == 200
    data = response.json()
    openai_entry = next(item for item in data if item["provider"] == "openai")
    assert openai_entry["configured"] is True
    assert openai_entry["label"] == "OpenAI"


@pytest.mark.asyncio
async def test_list_api_keys_short_key_masked(client, monkeypatch):
    """Short keys still report configured=True (presence only; the value is never returned)."""
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


# --- SF-74: secure API-key configuration security invariants ---

_ALL_PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "stability": "STABILITY_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "groq": "GROQ_API_KEY",
}
_ALLOWED_ITEM_KEYS = {"provider", "label", "configured"}
_FORBIDDEN_ITEM_KEYS = {"key", "value", "secret", "token", "masked", "api_key", "env", "env_var"}


@pytest.mark.asyncio
async def test_settings_requires_authentication():
    """Unauthenticated GET must be rejected and leak no provider status."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/creator/settings/api-keys")
    assert response.status_code in {401, 403}
    assert "provider" not in response.text


@pytest.mark.asyncio
async def test_settings_item_schema_is_exactly_presence_only(client):
    """Each item exposes exactly {provider,label,configured} — no secret-bearing fields."""
    response = await client.get("/api/creator/settings/api-keys")
    data = response.json()
    for item in data:
        assert set(item.keys()) == _ALLOWED_ITEM_KEYS
        assert _FORBIDDEN_ITEM_KEYS.isdisjoint(item.keys())


@pytest.mark.asyncio
async def test_settings_never_echoes_any_raw_secret_across_all_providers(client, monkeypatch):
    """Real-looking keys for every provider must never appear in the serialized response."""
    secrets = {
        env: f"sk-{provider}-real-secret-{'x' * 40}"
        for provider, env in _ALL_PROVIDER_ENV.items()
    }
    for env, secret in secrets.items():
        monkeypatch.setenv(env, secret)
    response = await client.get("/api/creator/settings/api-keys")
    body = response.text
    for secret in secrets.values():
        assert secret not in body
    for provider, env in _ALL_PROVIDER_ENV.items():
        entry = next(item for item in response.json() if item["provider"] == provider)
        assert entry["configured"] is True


@pytest.mark.asyncio
async def test_settings_returns_no_masked_representation(client, monkeypatch):
    """Presence-only contract: not even a masked prefix/suffix of the key is disclosed."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-abcdEFGH1234567890zyxw")
    response = await client.get("/api/creator/settings/api-keys")
    for fragment in ("sk-abcd", "zyxw", "****", "sk-****", "...", "abcd"):
        assert fragment not in response.text


@pytest.mark.asyncio
async def test_settings_all_write_methods_are_405_and_leak_nothing(client, monkeypatch):
    """POST/PUT/PATCH/DELETE stay unsupported; a submitted key never reflects back."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-existing-configured-key-000000")
    before = (await client.get("/api/creator/settings/api-keys")).json()
    injected = "sk-attacker-injected-secret-999999"
    payload = {"provider": "openai", "api_key": injected}
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        response = await client.request(method, "/api/creator/settings/api-keys", json=payload)
        assert response.status_code == 405
        assert injected not in response.text
        assert "sk-existing-configured-key" not in response.text
    after = (await client.get("/api/creator/settings/api-keys")).json()
    assert after == before
    assert injected not in (await client.get("/api/creator/settings/api-keys")).text


@pytest.mark.asyncio
async def test_settings_get_does_not_log_secret(client, monkeypatch, caplog):
    """The route must not write key material to logs."""
    secret = "sk-should-never-be-logged-abcdef123456"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    with caplog.at_level(0):
        await client.get("/api/creator/settings/api-keys")
    for record in caplog.records:
        assert secret not in record.getMessage()
        assert secret not in str(record.args or "")
