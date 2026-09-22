"""SF-73: provider-configuration view model for first-run setup.

build_provider_config_view merges the two existing inventories — credential presence
(configured) and model/provider health (available/invalid) — into one clear
per-provider state, over the APPROVED provider allowlist only. It is a PURE function
of already-sanitized facts (canonical provider name, category, is_local,
requires_gpu, healthy), so the raw registry endpoints are stripped BEFORE the pure
boundary and can never leak. The view carries only provider names, labels,
env-var-NAME guidance, categories, local/remote flags, a coarse configured status,
and actionable hints — never a secret value and never an internal endpoint URL.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from creator_service.provider_config_view import (
    ApprovedCredential,
    ProviderCatalogFact,
    ProviderConfigStatus,
    ProviderConfigView,
    build_provider_config_view,
)
from creator_service.setup_wizard import ModelCategory

# The approved credential providers (mirrors api_keys._KEY_MAP), env var NAMES only.
_APPROVED = {
    "openai": ApprovedCredential(provider="openai", label="OpenAI", env_var="OPENAI_API_KEY"),
    "anthropic": ApprovedCredential(provider="anthropic", label="Anthropic", env_var="ANTHROPIC_API_KEY"),
    "google": ApprovedCredential(provider="google", label="Google", env_var="GOOGLE_API_KEY"),
    "stability": ApprovedCredential(provider="stability", label="Stability AI", env_var="STABILITY_API_KEY"),
    "elevenlabs": ApprovedCredential(provider="elevenlabs", label="ElevenLabs", env_var="ELEVENLABS_API_KEY"),
    "groq": ApprovedCredential(provider="groq", label="Groq", env_var="GROQ_API_KEY"),
}


def _fact(
    provider: str,
    category: ModelCategory,
    *,
    is_local: bool = False,
    requires_gpu: bool = False,
    healthy: bool = True,
    configured_unverified: bool = False,
) -> ProviderCatalogFact:
    return ProviderCatalogFact(
        provider=provider,
        category=category,
        is_local=is_local,
        requires_gpu=requires_gpu,
        healthy=healthy,
        configured_unverified=configured_unverified,
    )


def _build(
    *, configured: set[str], facts: list[ProviderCatalogFact]
) -> ProviderConfigView:
    return build_provider_config_view(
        approved_credentials=_APPROVED,
        configured_providers=configured,
        provider_facts=facts,
    )


def _state(view: ProviderConfigView, provider: str):
    for state in view.providers:
        if state.provider == provider:
            return state
    raise AssertionError(f"provider {provider} not in view")


# ------------------------- 1. approved-only output -------------------------


def test_arbitrary_provider_is_disclosed_as_unknown_not_configurable() -> None:
    view = _build(
        configured={"evil_provider", "openai"},
        facts=[_fact("evil_provider", ModelCategory.LLM), _fact("openai", ModelCategory.LLM)],
    )
    providers = {s.provider for s in view.providers}
    unknown = _state(view, "evil_provider")
    assert unknown.status is ProviderConfigStatus.UNKNOWN
    assert unknown.configured is False
    assert unknown.env_var is None
    assert "openai" in providers


# ------------------------- 2. groq inventory complete -------------------------


def test_groq_is_an_approved_provider_in_the_view() -> None:
    view = _build(configured={"groq"}, facts=[_fact("groq", ModelCategory.STT)])
    groq = _state(view, "groq")
    assert groq.env_var == "GROQ_API_KEY"
    assert ModelCategory.STT in groq.categories


# ------------------------- 3. configured + available (remote, multi-category) -------------------------


def test_configured_available_remote_collapses_multiple_categories() -> None:
    view = _build(
        configured={"openai"},
        facts=[
            _fact("openai", ModelCategory.LLM),
            _fact("openai", ModelCategory.IMAGE),
            _fact("openai", ModelCategory.TTS),
        ],
    )
    openai = _state(view, "openai")
    assert openai.status is ProviderConfigStatus.CONFIGURED_AVAILABLE
    assert openai.categories == (ModelCategory.LLM, ModelCategory.IMAGE, ModelCategory.TTS)
    # one row per provider, no duplicates
    assert [s.provider for s in view.providers].count("openai") == 1


# ------------------------- 4. configured + unavailable (invalid) -------------------------


def test_configured_but_unhealthy_is_configured_unavailable_without_endpoint() -> None:
    view = _build(
        configured={"anthropic"},
        facts=[_fact("anthropic", ModelCategory.LLM, healthy=False)],
    )
    anthropic = _state(view, "anthropic")
    assert anthropic.status is ProviderConfigStatus.CONFIGURED_UNAVAILABLE
    # actionable hint does not claim the key is bad and does not leak an endpoint
    assert "unavailable" in anthropic.hint.lower() or "unreachable" in anthropic.hint.lower()
    assert "http" not in anthropic.hint
    assert "malformed" not in anthropic.hint.lower()


# ------------------------- 4b. configured + UNVERIFIED (key present, not probed) -------------------------


def test_configured_unverified_remote_is_distinct_from_available_and_unavailable() -> None:
    # A remote key present but only CONFIGURED (not HTTP-probed HEALTHY) is honest
    # as "configured; not verified" — never "ready" and never "unavailable".
    view = _build(
        configured={"openai"},
        facts=[_fact("openai", ModelCategory.LLM, healthy=False, configured_unverified=True)],
    )
    openai = _state(view, "openai")
    assert openai.status is ProviderConfigStatus.CONFIGURED_UNVERIFIED
    assert openai.configured is True
    assert "not" in openai.hint.lower() and "verif" in openai.hint.lower()
    assert "ready" not in openai.hint.lower()
    assert "unavailable" not in openai.hint.lower()
    assert "http" not in openai.hint


def test_verified_healthy_outranks_unverified_for_same_provider() -> None:
    # If any category probed HEALTHY, the provider is AVAILABLE even if another
    # category is only configured-unverified.
    view = _build(
        configured={"openai"},
        facts=[
            _fact("openai", ModelCategory.LLM, healthy=True),
            _fact("openai", ModelCategory.IMAGE, healthy=False, configured_unverified=True),
        ],
    )
    openai = _state(view, "openai")
    assert openai.status is ProviderConfigStatus.CONFIGURED_AVAILABLE


def test_unverified_outranks_unavailable_for_same_provider() -> None:
    # configured-unverified beats a hard-unavailable category: the provider is not
    # known-bad, so it must not read "unavailable".
    view = _build(
        configured={"openai"},
        facts=[
            _fact("openai", ModelCategory.LLM, healthy=False, configured_unverified=True),
            _fact("openai", ModelCategory.IMAGE, healthy=False),
        ],
    )
    openai = _state(view, "openai")
    assert openai.status is ProviderConfigStatus.CONFIGURED_UNVERIFIED


# ------------------------- 5. not configured (remote) -------------------------


def test_not_configured_remote_names_the_env_var_to_set() -> None:
    view = _build(configured=set(), facts=[_fact("stability", ModelCategory.IMAGE)])
    stability = _state(view, "stability")
    assert stability.status is ProviderConfigStatus.NOT_CONFIGURED
    assert "STABILITY_API_KEY" in stability.hint
    assert stability.configured is False


# ------------------------- 6/7. local providers: healthy vs unhealthy -------------------------


def test_healthy_local_provider_needs_no_env_var() -> None:
    view = _build(
        configured=set(),
        facts=[_fact("ollama", ModelCategory.LLM, is_local=True, healthy=True)],
    )
    ollama = _state(view, "ollama")
    assert ollama.is_local is True
    assert ollama.env_var is None
    assert ollama.status is ProviderConfigStatus.CONFIGURED_AVAILABLE


def test_unhealthy_local_provider_points_at_the_service_not_a_key() -> None:
    view = _build(
        configured=set(),
        facts=[_fact("stable-diffusion", ModelCategory.IMAGE, is_local=True, healthy=False)],
    )
    sd = _state(view, "stable-diffusion")
    assert sd.status is ProviderConfigStatus.CONFIGURED_UNAVAILABLE
    assert "service" in sd.hint.lower()
    assert "API_KEY" not in sd.hint


# ------------------------- 8. provider-type collapse -------------------------


def test_openai_categories_collapse_under_one_provider() -> None:
    # The caller supplies canonical provider names already; assert the merge groups
    # every category fact for one provider into a single provider row.
    view = _build(
        configured={"openai"},
        facts=[
            _fact("openai", ModelCategory.LLM),
            _fact("openai", ModelCategory.IMAGE),
            _fact("openai", ModelCategory.TTS),
        ],
    )
    assert len([s for s in view.providers if s.provider == "openai"]) == 1


# ------------------------- 9. mixed availability within one provider -------------------------


def test_provider_is_available_if_any_category_is_healthy() -> None:
    # openai LLM healthy, IMAGE unhealthy -> provider is configured+available (at
    # least one usable capability), but the per-category health is preserved.
    view = _build(
        configured={"openai"},
        facts=[
            _fact("openai", ModelCategory.LLM, healthy=True),
            _fact("openai", ModelCategory.IMAGE, healthy=False),
        ],
    )
    openai = _state(view, "openai")
    assert openai.status is ProviderConfigStatus.CONFIGURED_AVAILABLE
    assert openai.unavailable_categories == (ModelCategory.IMAGE,)


# ------------------------- 10. endpoint/secret non-exposure -------------------------


def test_view_has_no_endpoint_or_secret_fields() -> None:
    view = _build(configured={"openai"}, facts=[_fact("openai", ModelCategory.LLM)])
    forbidden = {"endpoint", "url", "base_url", "hostname", "health_key", "api_key", "secret", "value"}
    for state in view.providers:
        assert forbidden.isdisjoint(asdict(state).keys())


def test_serialized_view_leaks_no_secret_or_endpoint() -> None:
    view = _build(
        configured={"openai"},
        facts=[_fact("openai", ModelCategory.LLM), _fact("ollama", ModelCategory.LLM, is_local=True)],
    )
    blob = json.dumps(asdict(view), default=str)
    for leak in (
        "sk-test-openai-secret",
        "http://ollama:11434",
        "api.openai.com",
        "api.groq.com",
        "stable-diffusion",
        ":11434",
        ":7860",
    ):
        assert leak not in blob


# ------------------------- 11. determinism / order -------------------------


def test_providers_are_ordered_stably_by_the_approved_allowlist() -> None:
    a = _build(
        configured={"groq", "openai"},
        facts=[_fact("groq", ModelCategory.STT), _fact("openai", ModelCategory.LLM)],
    )
    b = _build(
        configured={"openai", "groq"},
        facts=[_fact("openai", ModelCategory.LLM), _fact("groq", ModelCategory.STT)],
    )
    assert [s.provider for s in a.providers] == [s.provider for s in b.providers]


# ------------------------- 12. SF-72 category consistency -------------------------


def test_categories_use_the_setup_wizard_model_category_enum() -> None:
    view = _build(configured={"groq"}, facts=[_fact("groq", ModelCategory.STT)])
    for state in view.providers:
        for category in state.categories:
            assert isinstance(category, ModelCategory)
