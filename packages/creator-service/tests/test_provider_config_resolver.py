import json
from dataclasses import asdict

import pytest
from creator_provider.registry import ModelCatalogEntry, ProviderCategory, ProviderRegistry
from creator_service.model_health_service import ModelHealthResult, ModelStatus
from creator_service.provider_config_view import resolve_provider_config_view


class FakeHealthService:
    async def check_model(
        self, model_name: str, *, endpoint: str | None = None,
    ) -> ModelHealthResult:
        return ModelHealthResult(model_name, endpoint or model_name, ModelStatus.HEALTHY)


def registry() -> ProviderRegistry:
    result = ProviderRegistry()
    for entry in (
        ModelCatalogEntry("script", "openai_llm", "https://api.openai.com", ProviderCategory.LLM, is_local=False),
        ModelCatalogEntry("stt", "groq_stt", "https://api.groq.com/openai/v1", ProviderCategory.STT, is_local=False),
        ModelCatalogEntry("local", "ollama", "http://ollama:11434", ProviderCategory.LLM),
        ModelCatalogEntry("image", "sd_local", "http://stable-diffusion:7860", ProviderCategory.IMAGE),
    ):
        result.register_model(entry)
    return result


@pytest.mark.asyncio
async def test_resolver_produces_a_view_from_raw_registry_entries_with_endpoints() -> None:
    view = await resolve_provider_config_view(
        registry=registry(), health_service=FakeHealthService(), configured_providers={"openai", "groq"},
    )
    assert {s.provider for s in view.providers} == {"openai", "groq", "ollama", "sd_local"}


@pytest.mark.asyncio
async def test_resolver_output_never_leaks_an_endpoint_even_from_raw_entries() -> None:
    view = await resolve_provider_config_view(
        registry=registry(), health_service=FakeHealthService(), configured_providers={"openai"},
    )
    blob = json.dumps(asdict(view), default=str)
    for leak in ("api.openai.com", "api.groq.com", "ollama:11434", "stable-diffusion", ":7860", "http://", "https://"):
        assert leak not in blob
