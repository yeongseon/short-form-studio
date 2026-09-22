# pyright: reportPrivateUsage=false

"""P0-2: registry-derived setup provider facts (single source of truth).

Locks that setup readiness is computed from the registry (which already knows
each provider's category, local/remote, and health) instead of a duplicated,
drifting provider->category map. A remote key present satisfies its category
(configured is usable-enough to attempt); a local provider satisfies only when
its service actually probes HEALTHY; an UNHEALTHY configured/attempted provider
is surfaced as unhealthy; a local UNKNOWN provider is neither satisfied nor
counted as a configured failure.
"""

import pytest
from creator_service.model_health_service import ModelStatus
from creator_service.provider_readiness import (
    SetupProviderFacts,
    resolve_setup_provider_facts,
)
from creator_service.setup_wizard import ModelCategory


class _Entry:
    def __init__(self, provider_type, endpoint, category, is_local, requires_gpu=False):
        self.provider_type = provider_type
        self.endpoint = endpoint
        self.category = _Cat(category)
        self.is_local = is_local
        self.requires_gpu = requires_gpu


class _Cat:
    def __init__(self, value: str) -> None:
        self.value = value


class _Registry:
    def __init__(self, entries):
        self._entries = entries

    def list_models(self, category=None):
        return self._entries


class _Result:
    def __init__(self, status):
        self.status = status


class _Health:
    def __init__(self, by_host):
        self._by_host = by_host

    async def check_model(self, host):
        return _Result(self._by_host.get(host, ModelStatus.UNKNOWN))


def _registry_default():
    return _Registry(
        [
            _Entry("groq_llm", "https://api.groq.com", "llm", False),
            _Entry("groq_stt", "https://api.groq.com/openai/v1", "stt", False),
            _Entry("openai_llm", "https://api.openai.com", "llm", False),
            _Entry("ollama", "http://ollama:11434", "llm", True),
            _Entry("sd_local", "http://stable-diffusion:7860", "image", True),
        ]
    )


# --- registry is the SSOT for provider->category (Groq LLM no longer dropped) ---


@pytest.mark.asyncio
async def test_groq_llm_capability_is_not_dropped() -> None:
    # The registry has groq_llm + groq_stt -> canonical "groq" covers LLM and STT.
    # A key-configured groq must satisfy BOTH categories (the old duplicated map
    # dropped groq LLM).
    facts = await resolve_setup_provider_facts(
        registry=_registry_default(),
        health_service=_Health({"api.groq.com": ModelStatus.CONFIGURED}),
        configured_remote_providers={"groq"},
    )
    assert isinstance(facts, SetupProviderFacts)
    assert "groq" in facts.category_status[ModelCategory.LLM]
    assert "groq" in facts.category_status[ModelCategory.STT]


@pytest.mark.asyncio
async def test_remote_key_present_satisfies_its_category() -> None:
    facts = await resolve_setup_provider_facts(
        registry=_registry_default(),
        health_service=_Health({"api.openai.com": ModelStatus.CONFIGURED}),
        configured_remote_providers={"openai"},
    )
    assert "openai" in facts.category_status[ModelCategory.LLM]
    assert "openai" in facts.configured_providers


@pytest.mark.asyncio
async def test_remote_key_absent_does_not_satisfy() -> None:
    facts = await resolve_setup_provider_facts(
        registry=_registry_default(),
        health_service=_Health({}),
        configured_remote_providers=set(),
    )
    assert "openai" not in facts.category_status.get(ModelCategory.LLM, ())
    assert "openai" not in facts.configured_providers


# --- local providers satisfy only when HEALTHY (no API key) ---


@pytest.mark.asyncio
async def test_local_healthy_satisfies_without_api_key() -> None:
    facts = await resolve_setup_provider_facts(
        registry=_registry_default(),
        health_service=_Health({"ollama": ModelStatus.HEALTHY}),
        configured_remote_providers=set(),
    )
    assert "ollama" in facts.category_status[ModelCategory.LLM]
    assert "ollama" in facts.configured_providers
    assert "ollama" not in facts.unhealthy_providers


@pytest.mark.asyncio
async def test_local_unhealthy_does_not_satisfy_and_is_unhealthy() -> None:
    facts = await resolve_setup_provider_facts(
        registry=_registry_default(),
        health_service=_Health({"stable-diffusion": ModelStatus.UNHEALTHY}),
        configured_remote_providers=set(),
    )
    assert "sd_local" not in facts.category_status.get(ModelCategory.IMAGE, ())
    assert "sd_local" in facts.unhealthy_providers


@pytest.mark.asyncio
async def test_local_unknown_is_neither_satisfied_nor_configured_failure() -> None:
    # UNKNOWN local (e.g. an unregistered health endpoint) must not become a
    # configured failure in this lane (that is the separate P2-7 endpoint bug).
    facts = await resolve_setup_provider_facts(
        registry=_Registry([_Entry("cosyvoice_tts", "http://tts-cosyvoice:50000", "tts", True)]),
        health_service=_Health({}),
        configured_remote_providers=set(),
    )
    assert "cosyvoice_tts" not in facts.configured_providers
    assert "cosyvoice_tts" not in facts.unhealthy_providers
    assert ModelCategory.TTS not in facts.category_status or not facts.category_status[ModelCategory.TTS]


# --- category key present == configured, non-empty tuple == satisfied ---


@pytest.mark.asyncio
async def test_configured_but_all_unhealthy_keeps_category_key_empty() -> None:
    # A configured remote whose only category probed UNHEALTHY keeps the category
    # key (configured) but empty (not satisfied) — preserving the wizard's
    # configured-but-failing-checks distinction.
    facts = await resolve_setup_provider_facts(
        registry=_Registry([_Entry("openai_llm", "https://api.openai.com", "llm", False)]),
        health_service=_Health({"api.openai.com": ModelStatus.UNHEALTHY}),
        configured_remote_providers={"openai"},
    )
    assert ModelCategory.LLM in facts.category_status
    assert facts.category_status[ModelCategory.LLM] == ()
    assert "openai" in facts.unhealthy_providers


@pytest.mark.asyncio
async def test_no_endpoint_or_secret_in_facts() -> None:
    facts = await resolve_setup_provider_facts(
        registry=_registry_default(),
        health_service=_Health({"api.groq.com": ModelStatus.CONFIGURED}),
        configured_remote_providers={"groq"},
    )
    blob = f"{facts.configured_providers}{facts.category_status}{facts.unhealthy_providers}"
    for leak in ("http", "api.groq.com", "11434", "7860", "sk-"):
        assert leak not in blob
