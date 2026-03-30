from unittest.mock import AsyncMock

import pytest

from creator_service.model_catalog_service import ModelCatalogService
from creator_service.model_health_service import ModelHealthResult, ModelStatus
from creator_provider.registry import ProviderRegistry

@pytest.fixture
def registry():
    return ProviderRegistry.create_default()


@pytest.fixture
def health_service() -> AsyncMock:
    service = AsyncMock()
    status_by_provider = {
        "ollama": ModelStatus.HEALTHY,
        "stable-diffusion": ModelStatus.UNHEALTHY,
        "tts-qwen3": ModelStatus.UNKNOWN,
        "stt-whisper": ModelStatus.HEALTHY,
    }

    async def check_model(name: str) -> ModelHealthResult:
        status = status_by_provider.get(name, ModelStatus.UNKNOWN)
        return ModelHealthResult(
            model_name=name,
            endpoint=f"http://{name}:1234",
            status=status,
        )

    service.check_model.side_effect = check_model
    return service


class TestModelCatalogService:
    @pytest.mark.asyncio
    async def test_list_models_returns_all_categories(self, registry, health_service: AsyncMock):
        service = ModelCatalogService(registry, health_service)

        result = await service.list_models()

        assert set(result.keys()) == {"script_models", "image_models", "tts_models", "stt_models"}
        assert len(result["script_models"]) == 1
        assert len(result["image_models"]) == 1
        assert len(result["tts_models"]) == 1
        assert len(result["stt_models"]) == 1

        script_model = result["script_models"][0]
        assert script_model["key"] == "qwen3-4b"
        assert script_model["label"] == "Qwen3 4B (Local)"
        assert script_model["provider_type"] == "ollama"
        assert script_model["is_local"] is True
        assert script_model["requires_gpu"] is True
        assert script_model["status"] == "available"

        image_model = result["image_models"][0]
        assert image_model["status"] == "unavailable"
        assert image_model["label"] == "Stable Diffusion 1.5 (Local)"

        tts_model = result["tts_models"][0]
        assert tts_model["status"] == "unknown"
        assert tts_model["label"] == "Qwen TTS (Local)"

        stt_model = result["stt_models"][0]
        assert stt_model["label"] == "Whisper Medium (Local)"

    @pytest.mark.asyncio
    async def test_list_models_filters_script_category(self, registry, health_service: AsyncMock):
        service = ModelCatalogService(registry, health_service)

        result = await service.list_models(category="script")

        assert len(result["script_models"]) == 1
        assert result["script_models"][0]["key"] == "qwen3-4b"
        assert result["image_models"] == []
        assert result["tts_models"] == []
        assert result["stt_models"] == []

    @pytest.mark.asyncio
    async def test_list_models_filters_image_category(self, registry, health_service: AsyncMock):
        service = ModelCatalogService(registry, health_service)

        result = await service.list_models(category="image")

        assert len(result["image_models"]) == 1
        assert result["image_models"][0]["key"] == "sd15"
        assert result["script_models"] == []
        assert result["tts_models"] == []
        assert result["stt_models"] == []

    @pytest.mark.asyncio
    async def test_get_status_returns_expected_shape(self, registry, health_service: AsyncMock):
        service = ModelCatalogService(registry, health_service)

        result = await service.get_status()

        assert set(result.keys()) == {"providers", "gpu_lock"}
        assert isinstance(result["providers"], list)
        assert len(result["providers"]) == 4

        provider = result["providers"][0]
        assert set(provider.keys()) == {"name", "endpoint", "healthy", "loaded_model", "gpu_locked"}
        assert provider["loaded_model"] is None
        assert provider["gpu_locked"] is False

        # Provider names should match health service keys (Docker hostnames),
        # not provider_type values from registry
        provider_names = {p["name"] for p in result["providers"]}
        assert provider_names == {"ollama", "stable-diffusion", "tts-qwen3", "stt-whisper"}
        assert set(provider.keys()) == {"name", "endpoint", "healthy", "loaded_model", "gpu_locked"}
        assert provider["loaded_model"] is None
        assert provider["gpu_locked"] is False

        assert result["gpu_lock"] == {
            "active": False,
            "holder": None,
            "ttl_remaining": None,
        }

    @pytest.mark.asyncio
    async def test_model_entries_have_required_fields(self, registry, health_service: AsyncMock):
        service = ModelCatalogService(registry, health_service)

        result = await service.list_models()

        required_fields = {"key", "label", "provider_type", "is_local", "requires_gpu", "status"}
        all_entries = (
            result["script_models"]
            + result["image_models"]
            + result["tts_models"]
            + result["stt_models"]
        )

        for entry in all_entries:
            assert set(entry.keys()) == required_fields

    @pytest.mark.asyncio
    async def test_health_key_matches_health_service_keys(
        self, registry, health_service: AsyncMock
    ):
        """Verify _health_key() produces keys that ModelHealthService recognises."""
        service = ModelCatalogService(registry, health_service)

        await service.list_models()

        called_keys = {call.args[0] for call in health_service.check_model.call_args_list}
        expected_keys = {"ollama", "stable-diffusion", "tts-qwen3", "stt-whisper"}
        assert called_keys == expected_keys
