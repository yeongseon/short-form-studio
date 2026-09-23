"""SF-73: provider-configuration view model for first-run setup.

build_provider_config_view merges the two existing inventories — credential presence
(configured) and model/provider health (available/unavailable) — into one clear
per-provider state, over the APPROVED provider allowlist only. It is a PURE function
of already-sanitized facts (canonical provider name, category, is_local,
requires_gpu, healthy), so the raw registry endpoints are stripped BEFORE the pure
boundary and can never leak. The view carries only provider names, labels,
env-var-NAME guidance, categories, local/remote flags, a coarse configured status,
and actionable hints — never a secret value and never an internal endpoint URL.
Unrecognized remote providers are disclosed as unknown, never as configurable.
"""

from __future__ import annotations

import enum
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from creator_service.model_health_service import ModelStatus
from creator_service.provider_facts import HealthReader, ModelRegistry, resolve_provider_facts
from creator_service.provider_metadata import (
    KEYLESS_REMOTE_PROVIDERS, REMOTE_CREDENTIALS, UNSUPPORTED_REMOTE_PROVIDERS,
)
from creator_service.setup_wizard import ModelCategory

_CATEGORY_ORDER = (
    ModelCategory.LLM,
    ModelCategory.IMAGE,
    ModelCategory.TTS,
    ModelCategory.STT,
)


class ProviderConfigStatus(enum.Enum):
    UNKNOWN = "unknown"
    NOT_CONFIGURED = "not_configured"
    CONFIGURED_AVAILABLE = "configured_available"
    CONFIGURED_UNVERIFIED = "configured_unverified"
    CONFIGURED_UNAVAILABLE = "configured_unavailable"


@dataclass(frozen=True)
class ApprovedCredential:
    provider: str
    label: str
    env_var: str


APPROVED_CREDENTIALS: dict[str, ApprovedCredential] = {
    provider: ApprovedCredential(provider, credential.label, credential.env_var)
    for provider, credential in REMOTE_CREDENTIALS.items()
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
    unknown: bool = False


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
    other_providers = sorted(p for p in facts_by_provider if p not in approved_credentials)
    for provider in [*approved_order, *other_providers]:
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
    available_categories = {f.category for f in facts if f.healthy or f.configured_unverified or f.unknown}
    unavailable = categories - available_categories
    any_healthy = any(f.healthy for f in facts)
    any_unverified = any(f.configured_unverified for f in facts)

    present = is_local or provider in KEYLESS_REMOTE_PROVIDERS or is_key_configured
    label = credential.label if credential is not None else provider
    env_var = None if is_local else (credential.env_var if credential is not None else None)

    unsupported = not is_local and credential is None and provider not in KEYLESS_REMOTE_PROVIDERS
    if unsupported:
        present = False
        unavailable = set()
        status = ProviderConfigStatus.UNKNOWN
        hint = UNSUPPORTED_REMOTE_PROVIDERS.get(
            provider, "Provider readiness is unsupported; authentication and availability are unknown",
        )
    elif not present:
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
    elif any(f.unknown for f in facts):
        status = ProviderConfigStatus.UNKNOWN
        hint = f"{label} has not been checked; availability is unknown"
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
    registry: ModelRegistry,
    health_service: HealthReader,
    configured_providers: Collection[str],
) -> ProviderConfigView:
    """Reduce shared health facts to the endpoint-free provider configuration view."""
    facts: list[ProviderCatalogFact] = []
    for fact in await resolve_provider_facts(registry.list_models(), health_service):
        facts.append(
            ProviderCatalogFact(
                provider=fact.provider,
                category=ModelCategory(fact.entry.category.value),
                is_local=fact.is_local,
                requires_gpu=fact.entry.requires_gpu,
                healthy=fact.status is ModelStatus.HEALTHY,
                configured_unverified=fact.status is ModelStatus.CONFIGURED,
                unknown=fact.status is ModelStatus.UNKNOWN,
            )
        )
    return build_provider_config_view(
        approved_credentials=APPROVED_CREDENTIALS,
        configured_providers=configured_providers,
        provider_facts=facts,
    )
