from collections import Counter
from unittest.mock import patch

import httpx
import anyio
import pytest
from creator_provider.registry import ModelCatalogEntry, ProviderCategory, ProviderRegistry
from creator_service.model_catalog_service import ModelCatalogService
from creator_service.model_health_service import ModelHealthResult, ModelHealthService, ModelStatus
from creator_service.provider_config_view import resolve_provider_config_view
from creator_service.provider_readiness import resolve_setup_provider_facts
from creator_service.setup_wizard import ModelCategory


class CountingHealth:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    async def check_model(self, model_name: str, *, endpoint: str | None = None) -> ModelHealthResult:
        self.calls[model_name] += 1
        return ModelHealthResult(model_name, endpoint or model_name, ModelStatus.CONFIGURED)


def remote_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    for key, provider, category in (
        ("script-a", "openai_llm", ProviderCategory.LLM),
        ("script-b", "openai_llm", ProviderCategory.LLM),
        ("image-a", "openai_image", ProviderCategory.IMAGE),
    ):
        registry.register_model(ModelCatalogEntry(
            key, provider, "https://api.openai.com", category, is_local=False,
        ))
    return registry


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["catalog", "status", "config", "setup"])
async def test_one_probe_per_provider_when_multiple_models_share_it(surface: str) -> None:
    # Given multiple models and categories behind one provider.
    registry, health = remote_registry(), CountingHealth()
    # When each supported surface resolves readiness.
    if surface == "catalog":
        await ModelCatalogService(registry, health).list_models()
    elif surface == "status":
        await ModelCatalogService(registry, health).get_status()
    elif surface == "config":
        await resolve_provider_config_view(
            registry=registry, health_service=health, configured_providers={"openai"},
        )
    else:
        await resolve_setup_provider_facts(
            registry=registry, health_service=health, configured_remote_providers={"openai"},
        )
    # Then no repeated probe is issued within the request.
    assert health.calls == {"api.openai.com": 1}


@pytest.mark.asyncio
async def test_catalog_keeps_configured_remote_models_unverified() -> None:
    # Given credential presence without a successful health probe.
    catalog = ModelCatalogService(remote_registry(), CountingHealth())
    # When models are listed.
    result = await catalog.list_models()
    # Then availability is not fabricated.
    assert {m["status"] for m in result["script_models"]} == {"configured_unverified"}


@pytest.mark.asyncio
async def test_status_does_not_claim_configured_provider_is_healthy() -> None:
    # Given credential presence without a successful health probe.
    catalog = ModelCatalogService(remote_registry(), CountingHealth())
    # When provider status is requested.
    result = await catalog.get_status()
    # Then configured and verified are distinguishable on the wire.
    assert result["providers"] == [
        {"name": "api.openai.com", "healthy": False, "status": "configured_unverified"},
    ]


def keyless_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    for provider, category in (
        ("placeholder_image", ProviderCategory.IMAGE),
        ("edge_tts", ProviderCategory.TTS),
    ):
        registry.register_model(ModelCatalogEntry(
            provider, provider, "local", category, requires_gpu=False,
        ))
    return registry


@pytest.mark.asyncio
async def test_offline_and_keyless_remote_catalog_facts() -> None:
    # Given the legacy registry's local sentinel for both providers.
    catalog = ModelCatalogService(keyless_registry(), ModelHealthService())
    # When the catalog is resolved without network calls.
    with patch("httpx.AsyncClient", side_effect=AssertionError("unexpected network")):
        result = await catalog.list_models()
    # Then only the offline generator is available; Edge requires remote execution.
    assert result["image_models"][0]["status"] == "available"
    assert result["tts_models"][0]["status"] == "unknown"
    assert result["tts_models"][0]["is_local"] is False


@pytest.mark.asyncio
async def test_keyless_provider_config_is_not_a_missing_local_service() -> None:
    # Given no API keys and no remote probe.
    # When provider configuration is resolved.
    view = await resolve_provider_config_view(
        registry=keyless_registry(), health_service=ModelHealthService(), configured_providers=(),
    )
    # Then offline and unknown remote capabilities remain distinct.
    states = {state.provider: state for state in view.providers}
    assert states["placeholder_image"].status.value == "configured_available"
    edge = states["edge_tts"]
    assert (edge.status.value, edge.is_local, edge.env_var) == ("unknown", False, None)
    assert edge.configured is True
    assert edge.unavailable_categories == ()


@pytest.mark.asyncio
async def test_setup_counts_offline_images_but_not_unprobed_edge_tts() -> None:
    # Given keyless capabilities only.
    # When setup readiness is resolved.
    facts = await resolve_setup_provider_facts(
        registry=keyless_registry(), health_service=ModelHealthService(),
        configured_remote_providers=(),
    )
    # Then the offline capability satisfies IMAGE, not remote TTS.
    assert facts.category_status[ModelCategory.IMAGE] == ("placeholder_image",)
    assert not facts.category_status.get(ModelCategory.TTS)
    assert "edge_tts" not in facts.unhealthy_providers


@pytest.mark.asyncio
async def test_local_overrides_preserve_ports_paths_and_probe_types() -> None:
    # Given two services on the same host, with explicit registry overrides.
    registry = ProviderRegistry()
    registry.register_model(ModelCatalogEntry(
        "llm", "ollama", "http://127.0.0.1:19001/llm/", ProviderCategory.LLM,
    ))
    registry.register_model(ModelCatalogEntry(
        "image", "sd_local", "http://127.0.0.1:19002/image/", ProviderCategory.IMAGE,
    ))
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200)

    client_class = httpx.AsyncClient
    # When actual health code resolves the catalog through a wire-level transport.
    with patch("creator_service.model_health_service.httpx.AsyncClient",
               side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(respond))):
        result = await ModelCatalogService(registry, ModelHealthService()).list_models()
    # Then registry endpoints, not hostnames or stale defaults, determine the probes.
    assert set(requests) == {
        "http://127.0.0.1:19001/llm/api/tags",
        "http://127.0.0.1:19002/image/sdapi/v1/options",
    }
    assert result["script_models"][0]["status"] == "available"
    assert result["image_models"][0]["status"] == "available"


@pytest.mark.asyncio
async def test_remote_override_keeps_credential_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given an OpenAI-compatible endpoint override with a configured key.
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    registry = ProviderRegistry()
    registry.register_model(ModelCatalogEntry(
        "remote", "openai_llm", "https://custom.invalid/v1", ProviderCategory.LLM,
        is_local=False,
    ))
    # When catalog readiness is checked without sending any provider request.
    with patch("httpx.AsyncClient", side_effect=AssertionError("unexpected paid probe")):
        result = await ModelCatalogService(registry, ModelHealthService()).list_models()
    # Then a custom hostname does not lose the credential configuration.
    assert result["script_models"][0]["status"] == "configured_unverified"


@pytest.mark.asyncio
async def test_distinct_local_probes_run_concurrently() -> None:
    # Given two independent services whose replies wait for both requests.
    registry = ProviderRegistry()
    registry.register_model(ModelCatalogEntry(
        "llm", "ollama", "http://ollama:11434", ProviderCategory.LLM,
    ))
    registry.register_model(ModelCatalogEntry(
        "image", "sd_local", "http://stable-diffusion:7860", ProviderCategory.IMAGE,
    ))
    arrived: set[str] = set()
    both_arrived = anyio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        arrived.add(request.url.host)
        if len(arrived) == 2:
            both_arrived.set()
        await both_arrived.wait()
        return httpx.Response(200)

    client_class = httpx.AsyncClient
    # When one catalog request resolves both services.
    with anyio.fail_after(2), patch(
        "creator_service.model_health_service.httpx.AsyncClient",
        side_effect=lambda **kwargs: client_class(transport=httpx.MockTransport(respond)),
    ):
        result = await ModelCatalogService(registry, ModelHealthService()).list_models()
    # Then neither probe waits for another service's timeout.
    assert result["script_models"][0]["status"] == "available"
    assert result["image_models"][0]["status"] == "available"
