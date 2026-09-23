# pyright: reportMissingImports=false

from collections.abc import Sequence

import pytest
from fastapi.routing import APIRoute
from shorts_api.main import models_router


class StubModelCatalogService:
    def __init__(self) -> None:
        self.list_models_calls: list[str | None] = []
        self.status_calls = 0

    async def list_models(self, category: str | None = None) -> dict[str, list[dict[str, object]]]:
        self.list_models_calls.append(category)
        base = {
            "script_models": [
                {
                    "key": "qwen3-4b",
                    "label": "Qwen3 4B (Local)",
                    "provider_type": "ollama",
                    "is_local": True,
                    "requires_gpu": True,
                    "status": "available",
                }
            ],
            "image_models": [
                {
                    "key": "sd15",
                    "label": "Stable Diffusion 1.5 (Local)",
                    "provider_type": "sd_local",
                    "is_local": True,
                    "requires_gpu": True,
                    "status": "available",
                }
            ],
            "tts_models": [
                {
                    "key": "qwen3-tts",
                    "label": "Qwen3 TTS (Local)",
                    "provider_type": "qwen_tts",
                    "is_local": True,
                    "requires_gpu": True,
                    "status": "available",
                }
            ],
            "stt_models": [
                {
                    "key": "whisper-small",
                    "label": "Whisper Small (Local)",
                    "provider_type": "whisper",
                    "is_local": True,
                    "requires_gpu": True,
                    "status": "available",
                }
            ],
        }

        if category == "script":
            return {
                "script_models": base["script_models"],
                "image_models": [],
                "tts_models": [],
                "stt_models": [],
            }

        return base

    async def get_status(self) -> dict[str, object]:
        self.status_calls += 1
        return {
            "providers": [
                {
                    "name": "ollama",
                    "healthy": True,
                    "loaded_model": "qwen3-4b",
                    "gpu_locked": False,
                }
            ],
            "gpu_lock": {
                "active": False,
                "holder": None,
                "ttl_remaining": None,
            },
        }


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [route for route in routes if isinstance(route, APIRoute)]


@pytest.fixture
def stub_catalog_service(monkeypatch: pytest.MonkeyPatch) -> StubModelCatalogService:
    service = StubModelCatalogService()

    for route in _iter_api_routes(models_router.routes):
        if route.name in {"list_models", "get_model_status"}:
            monkeypatch.setitem(route.endpoint.__globals__, "model_catalog_service", service)

    return service


@pytest.mark.asyncio
async def test_list_models_returns_all_categories(client, stub_catalog_service: StubModelCatalogService):
    response = await client.get("/api/creator/models")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"script_models", "image_models", "tts_models", "stt_models"}
    assert stub_catalog_service.list_models_calls == [None]


@pytest.mark.asyncio
async def test_list_models_filters_by_script_category(client, stub_catalog_service: StubModelCatalogService):
    response = await client.get("/api/creator/models?category=script")

    assert response.status_code == 200
    body = response.json()
    assert len(body["script_models"]) == 1
    assert body["image_models"] == []
    assert body["tts_models"] == []
    assert body["stt_models"] == []
    assert stub_catalog_service.list_models_calls == ["script"]


@pytest.mark.asyncio
async def test_list_models_rejects_invalid_category(client, stub_catalog_service: StubModelCatalogService):
    response = await client.get("/api/creator/models?category=invalid")

    assert response.status_code == 400
    assert stub_catalog_service.list_models_calls == []


@pytest.mark.asyncio
async def test_model_status_returns_provider_and_gpu_lock(client, stub_catalog_service: StubModelCatalogService):
    response = await client.get("/api/creator/models/status")

    assert response.status_code == 200
    body = response.json()
    assert "providers" in body
    assert "gpu_lock" in body
    assert isinstance(body["providers"], list)
    assert isinstance(body["gpu_lock"], dict)
    for provider_entry in body["providers"]:
        assert "endpoint" not in provider_entry, (
            f"Provider '{provider_entry.get('name')}' leaks 'endpoint' field"
        )
    assert stub_catalog_service.status_calls == 1


# ------------------------- provider-config route (SF-73) -------------------------


class _StubEntry:
    def __init__(self, provider_type, endpoint, category, is_local, requires_gpu=False):
        self.provider_type = provider_type
        self.endpoint = endpoint
        self.category = category
        self.is_local = is_local
        self.requires_gpu = requires_gpu


class _StubCategory:
    def __init__(self, value: str) -> None:
        self.value = value


class _StubRegistry:
    def list_models(self):
        return [
            _StubEntry("openai_llm", "https://api.openai.com", _StubCategory("llm"), False),
            _StubEntry("groq_stt", "https://api.groq.com/openai/v1", _StubCategory("stt"), False),
            _StubEntry("ollama", "http://ollama:11434", _StubCategory("llm"), True),
            _StubEntry("sd_local", "http://stable-diffusion:7860", _StubCategory("image"), True),
        ]


class _StubResult:
    def __init__(self, status):
        self.status = status


class _StubHealthService:
    async def check_model(self, model_name: str, *, endpoint: str | None = None):
        from creator_service.model_health_service import ModelStatus

        return _StubResult(ModelStatus.HEALTHY)


@pytest.fixture
def stub_provider_config(monkeypatch: pytest.MonkeyPatch):
    for route in _iter_api_routes(models_router.routes):
        if route.name == "get_provider_config":
            monkeypatch.setitem(
                route.endpoint.__globals__, "get_default_registry", lambda: _StubRegistry()
            )
            monkeypatch.setitem(route.endpoint.__globals__, "_health_service", _StubHealthService())
            monkeypatch.setitem(
                route.endpoint.__globals__,
                "list_configured_providers",
                lambda: ["openai", "groq"],
            )


@pytest.mark.asyncio
async def test_provider_config_requires_authentication(stub_provider_config):
    from httpx import ASGITransport, AsyncClient
    from shorts_api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/creator/models/provider-config")

    assert response.status_code in {401, 403}


@pytest.mark.asyncio
async def test_provider_config_returns_states_without_leaking_endpoints_or_secrets(
    client, stub_provider_config
):
    response = await client.get("/api/creator/models/provider-config")

    assert response.status_code == 200
    body = response.json()
    assert "providers" in body
    providers = {p["provider"] for p in body["providers"]}
    assert {"openai", "groq", "ollama"} <= providers

    import json as _json

    blob = _json.dumps(body)
    # Raw registry entries carried real endpoints; the route must never surface them.
    for leak in ("api.openai.com", "api.groq.com", "ollama:11434", "stable-diffusion", ":7860", "http://", "https://"):
        assert leak not in blob
    for state in body["providers"]:
        for forbidden in ("endpoint", "url", "base_url", "hostname", "api_key", "secret", "value"):
            assert forbidden not in state
