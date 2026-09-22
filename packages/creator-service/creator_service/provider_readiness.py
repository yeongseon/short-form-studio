"""Setup eligibility permits configured remote attempts without claiming health."""

from collections.abc import Collection
from dataclasses import dataclass

from creator_service.model_health_service import ModelStatus
from creator_service.provider_facts import HealthReader, ModelRegistry, resolve_provider_facts
from creator_service.setup_wizard import ModelCategory


@dataclass(frozen=True, slots=True)
class SetupProviderFacts:
    configured_providers: tuple[str, ...]
    category_status: dict[ModelCategory, tuple[str, ...]]
    unhealthy_providers: tuple[str, ...]
    unknown_providers: tuple[str, ...] = ()


async def resolve_setup_provider_facts(
    *,
    registry: ModelRegistry,
    health_service: HealthReader,
    configured_remote_providers: Collection[str],
) -> SetupProviderFacts:
    configured: set[str] = set()
    unhealthy: set[str] = set()
    unknown: set[str] = set()
    categories: dict[ModelCategory, set[str]] = {}
    for fact in await resolve_provider_facts(registry.list_models(), health_service):
        if fact.status is ModelStatus.UNKNOWN:
            unknown.add(fact.provider)
        attempted = (
            fact.status in (ModelStatus.HEALTHY, ModelStatus.UNHEALTHY)
            if fact.is_local else fact.keyless or fact.provider in configured_remote_providers
        )
        if not attempted:
            continue
        configured.add(fact.provider)
        providers = categories.setdefault(ModelCategory(fact.entry.category.value), set())
        if fact.status is ModelStatus.HEALTHY or (
            not fact.is_local and fact.status is ModelStatus.CONFIGURED
        ):
            providers.add(fact.provider)
        if fact.status is ModelStatus.UNHEALTHY:
            unhealthy.add(fact.provider)
    return SetupProviderFacts(
        configured_providers=tuple(sorted(configured)),
        category_status={category: tuple(sorted(providers)) for category, providers in categories.items()},
        unhealthy_providers=tuple(sorted(unhealthy)),
        unknown_providers=tuple(sorted(unknown)),
    )
