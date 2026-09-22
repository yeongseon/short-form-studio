"""SF-73: provider-configuration view model for first-run setup.

build_provider_config_view merges the two existing inventories — credential presence
(configured) and model/provider health (available/unavailable) — into one clear
per-provider state, over the APPROVED provider allowlist only. It is a PURE function
of already-sanitized facts (canonical provider name, category, is_local,
requires_gpu, healthy), so the raw registry endpoints are stripped BEFORE the pure
boundary and can never leak. The view carries only provider names, labels,
env-var-NAME guidance, categories, local/remote flags, a coarse configured status,
and actionable hints — never a secret value and never an internal endpoint URL. An
unapproved provider is never surfaced as configurable.
"""

from __future__ import annotations

import enum
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from creator_service.model_health_service import ModelStatus
from creator_service.setup_wizard import ModelCategory

# Registry provider_type -> canonical config provider name. Multiple typed
# providers (openai_llm/openai_image/openai_tts) collapse to one config provider.
_PROVIDER_TYPE_TO_CANONICAL: dict[str, str] = {
    "openai_llm": "openai",
    "openai_image": "openai",
    "openai_tts": "openai",
    "anthropic_llm": "anthropic",
    "gemini_llm": "google",
    "google_image": "google",
    "stability_image": "stability",
    "elevenlabs_tts": "elevenlabs",
    "groq_llm": "groq",
    "groq_stt": "groq",
    "groq_svg_image": "groq",
    "ollama": "ollama",
    "sd_local": "sd_local",
    "qwen_tts": "qwen_tts",
    "cosyvoice_tts": "cosyvoice_tts",
    "edge_tts": "edge_tts",
    "whisper": "whisper",
    "placeholder_image": "placeholder_image",
    "codex_image": "codex_image",
    "huggingface_image": "huggingface_image",
    "pollinations_image": "pollinations_image",
}

_CATEGORY_FROM_REGISTRY_VALUE: dict[str, ModelCategory] = {
    "llm": ModelCategory.LLM,
    "image": ModelCategory.IMAGE,
    "tts": ModelCategory.TTS,
    "stt": ModelCategory.STT,
}

_CATEGORY_ORDER = (
    ModelCategory.LLM,
    ModelCategory.IMAGE,
    ModelCategory.TTS,
    ModelCategory.STT,
)


class ProviderConfigStatus(enum.Enum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED_AVAILABLE = "configured_available"
    CONFIGURED_UNVERIFIED = "configured_unverified"
    CONFIGURED_UNAVAILABLE = "configured_unavailable"


@dataclass(frozen=True)
class ApprovedCredential:
    provider: str
    label: str
    env_var: str


# The approved credential providers (mirrors creator_provider.api_keys._KEY_MAP),
# with the display label and env var NAME only — never a value.
APPROVED_CREDENTIALS: dict[str, ApprovedCredential] = {
    "openai": ApprovedCredential("openai", "OpenAI", "OPENAI_API_KEY"),
    "anthropic": ApprovedCredential("anthropic", "Anthropic", "ANTHROPIC_API_KEY"),
    "google": ApprovedCredential("google", "Google (Gemini / Imagen)", "GOOGLE_API_KEY"),
    "stability": ApprovedCredential("stability", "Stability AI", "STABILITY_API_KEY"),
    "elevenlabs": ApprovedCredential("elevenlabs", "ElevenLabs", "ELEVENLABS_API_KEY"),
    "groq": ApprovedCredential("groq", "Groq", "GROQ_API_KEY"),
}


@dataclass(frozen=True)
class ProviderCatalogFact:
    """A sanitized provider capability fact — NO endpoint, NO secret ever crosses here.

    ``healthy`` means the capability was actually verified reachable (a local
    service probe or a live remote check succeeded). ``configured_unverified`` means
    a remote key is present but was NOT probed for validity — configured, but not
    known-good. The two are distinct so the view never claims an unverified key is
    "ready", nor calls it "unavailable".
    """

    provider: str
    category: ModelCategory
    is_local: bool
    requires_gpu: bool
    healthy: bool
    configured_unverified: bool = False


@dataclass(frozen=True)
class ProviderConfigState:
    provider: str
    label: str
    env_var: str | None
    configured: bool
    is_local: bool
    requires_gpu: bool
    status: ProviderConfigStatus
    categories: tuple[ModelCategory, ...]
    unavailable_categories: tuple[ModelCategory, ...]
    hint: str


@dataclass(frozen=True)
class ProviderConfigView:
    providers: tuple[ProviderConfigState, ...]


def _ordered_categories(categories: set[ModelCategory]) -> tuple[ModelCategory, ...]:
    return tuple(c for c in _CATEGORY_ORDER if c in categories)


def _remote_unavailable_hint(label: str, env_var: str | None) -> str:
    # Actionable without claiming the key is malformed (we never probe key validity)
    # and without exposing an endpoint.
    if env_var is not None:
        return f"{label} is configured but currently unavailable — verify {env_var} is set and retry the provider check"
    return f"{label} is configured but currently unavailable — retry the provider check"


def build_provider_config_view(
    *,
    approved_credentials: Mapping[str, ApprovedCredential],
    configured_providers: Collection[str],
    provider_facts: Collection[ProviderCatalogFact],
) -> ProviderConfigView:
    """Merge credential presence + capability health into a per-provider config view.

    Only approved credential providers and providers that appear in the sanitized
    facts are surfaced. A remote provider is available when its key is configured and
    at least one category is healthy; a local provider is available when at least one
    category is healthy (no key needed). A configured/present provider whose
    capabilities are all unhealthy is CONFIGURED_UNAVAILABLE, with a hint that points
    at a key or a local service without ever exposing an endpoint or secret.
    """
    configured = set(configured_providers)

    facts_by_provider: dict[str, list[ProviderCatalogFact]] = {}
    for fact in provider_facts:
        facts_by_provider.setdefault(fact.provider, []).append(fact)

    states: list[ProviderConfigState] = []
    # Stable order: approved credential providers first (allowlist order), then any
    # local/keyless providers from the facts, sorted for determinism.
    approved_order = list(approved_credentials)
    local_only = sorted(
        p
        for p in facts_by_provider
        if p not in approved_credentials and all(f.is_local for f in facts_by_provider[p])
    )
    for provider in [*approved_order, *local_only]:
        facts = facts_by_provider.get(provider)
        if not facts:
            continue
        states.append(
            _state_for(
                provider=provider,
                facts=facts,
                credential=approved_credentials.get(provider),
                is_key_configured=provider in configured,
            )
        )

    return ProviderConfigView(providers=tuple(states))


def _state_for(
    *,
    provider: str,
    facts: list[ProviderCatalogFact],
    credential: ApprovedCredential | None,
    is_key_configured: bool,
) -> ProviderConfigState:
    is_local = all(f.is_local for f in facts)
    requires_gpu = any(f.requires_gpu for f in facts)
    categories = {f.category for f in facts}
    unavailable = {f.category for f in facts if not f.healthy and not f.configured_unverified}
    any_healthy = any(f.healthy for f in facts)
    any_unverified = any(f.configured_unverified for f in facts)

    # A remote provider is "present" only when its key is configured; a local
    # provider needs no key, so it is always present but gated by service health.
    present = is_local or is_key_configured
    label = credential.label if credential is not None else provider
    env_var = None if is_local else (credential.env_var if credential is not None else None)

    if not present:
        status = ProviderConfigStatus.NOT_CONFIGURED
        hint = (
            f"set {env_var} to enable {label}"
            if env_var is not None
            else f"configure {label} to enable it"
        )
    elif any_healthy:
        # Verified-healthy outranks unverified/unavailable.
        status = ProviderConfigStatus.CONFIGURED_AVAILABLE
        hint = f"{label} is ready"
    elif any_unverified:
        # Key present but not probed: honest middle state, neither ready nor bad.
        status = ProviderConfigStatus.CONFIGURED_UNVERIFIED
        hint = f"{label} is configured but not yet verified"
    else:
        status = ProviderConfigStatus.CONFIGURED_UNAVAILABLE
        hint = (
            f"{label} is configured but the local service is unavailable — check the service"
            if is_local
            else _remote_unavailable_hint(label, env_var)
        )

    return ProviderConfigState(
        provider=provider,
        label=label,
        env_var=env_var,
        configured=present,
        is_local=is_local,
        requires_gpu=requires_gpu,
        status=status,
        categories=_ordered_categories(categories),
        unavailable_categories=_ordered_categories(unavailable),
        hint=hint,
    )


async def resolve_provider_config_view(
    *,
    registry: Any,
    health_service: Any,
    configured_providers: Collection[str],
) -> ProviderConfigView:
    """Wire the registry + health service into the pure builder (endpoint-free).

    Each registry entry is health-checked and reduced to a sanitized
    ProviderCatalogFact: the endpoint URL is used only to derive the internal health
    lookup key and is NEVER carried onto the fact, so no endpoint can leak. The
    provider_type is collapsed to its canonical config provider name.
    """
    facts: list[ProviderCatalogFact] = []
    for entry in registry.list_models():
        category = _CATEGORY_FROM_REGISTRY_VALUE.get(
            getattr(entry.category, "value", str(entry.category))
        )
        if category is None:
            continue
        provider = _PROVIDER_TYPE_TO_CANONICAL.get(entry.provider_type, entry.provider_type)
        health_key = _health_lookup_key(entry)
        result = await health_service.check_model(health_key)
        # HEALTHY = actually verified reachable; CONFIGURED = remote key present but
        # not probed (honest "unverified", never counted as verified-healthy).
        facts.append(
            ProviderCatalogFact(
                provider=provider,
                category=category,
                is_local=entry.is_local,
                requires_gpu=entry.requires_gpu,
                healthy=result.status is ModelStatus.HEALTHY,
                configured_unverified=result.status is ModelStatus.CONFIGURED,
            )
        )
    return build_provider_config_view(
        approved_credentials=APPROVED_CREDENTIALS,
        configured_providers=configured_providers,
        provider_facts=facts,
    )


def _health_lookup_key(entry: Any) -> str:
    parsed = urlparse(entry.endpoint)
    return parsed.hostname or entry.provider_type
