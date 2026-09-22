"""P0-2: registry-derived setup provider facts (single source of truth).

The registry already knows each provider's category, local/remote flag, and
(via health probes) its reachability. This helper derives the setup-readiness
facts from it, replacing the duplicated, drifting provider->category maps that
lived in the route modules.

Readiness rules:
- A remote provider satisfies its category when its key is configured AND its
  health is HEALTHY or CONFIGURED (a present key is usable-enough to *attempt* a
  first draft; we do not have a cheap validity probe).
- A local provider satisfies its category only when it actually probes HEALTHY.
- A configured/attempted provider that probes UNHEALTHY is surfaced as unhealthy.
- A local UNKNOWN provider (e.g. an unregistered health endpoint) is neither
  satisfied nor counted as a configured failure here — that is a separate bug.

No endpoint URL or secret value ever crosses this boundary; only provider names,
categories, and health enums are read.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from creator_service.model_health_service import ModelStatus
from creator_service.provider_config_view import (
    _CATEGORY_FROM_REGISTRY_VALUE,
    _PROVIDER_TYPE_TO_CANONICAL,
)
from creator_service.setup_wizard import ModelCategory


@dataclass(frozen=True)
class SetupProviderFacts:
    configured_providers: tuple[str, ...]
    category_status: dict[ModelCategory, tuple[str, ...]]
    unhealthy_providers: tuple[str, ...]


def _health_lookup_key(entry: Any) -> str:
    parsed = urlparse(entry.endpoint)
    return parsed.hostname or entry.provider_type


async def resolve_setup_provider_facts(
    *,
    registry: Any,
    health_service: Any,
    configured_remote_providers: Collection[str],
) -> SetupProviderFacts:
    configured_remote = set(configured_remote_providers)

    configured: set[str] = set()
    unhealthy: set[str] = set()
    satisfied_by_category: dict[ModelCategory, set[str]] = {}
    configured_by_category: dict[ModelCategory, set[str]] = {}

    for entry in registry.list_models():
        category = _CATEGORY_FROM_REGISTRY_VALUE.get(
            getattr(entry.category, "value", str(entry.category))
        )
        if category is None:
            continue
        provider = _PROVIDER_TYPE_TO_CANONICAL.get(entry.provider_type, entry.provider_type)
        status = (await health_service.check_model(_health_lookup_key(entry))).status

        if entry.is_local:
            # A local provider is "attempted" only once its service is reachable
            # (HEALTHY) or explicitly failing (UNHEALTHY); UNKNOWN is ignored.
            if status is ModelStatus.HEALTHY:
                configured.add(provider)
                configured_by_category.setdefault(category, set())
                satisfied_by_category.setdefault(category, set()).add(provider)
            elif status is ModelStatus.UNHEALTHY:
                configured.add(provider)
                configured_by_category.setdefault(category, set())
                unhealthy.add(provider)
        else:
            if provider not in configured_remote:
                continue
            configured.add(provider)
            configured_by_category.setdefault(category, set())
            if status in (ModelStatus.HEALTHY, ModelStatus.CONFIGURED):
                satisfied_by_category.setdefault(category, set()).add(provider)
            elif status is ModelStatus.UNHEALTHY:
                unhealthy.add(provider)

    # A category key is present when at least one provider was configured/attempted
    # for it (configured), and its tuple lists only the providers that satisfy it.
    category_status: dict[ModelCategory, tuple[str, ...]] = {
        category: tuple(sorted(satisfied_by_category.get(category, set())))
        for category in configured_by_category
    }

    return SetupProviderFacts(
        configured_providers=tuple(sorted(configured)),
        category_status=category_status,
        unhealthy_providers=tuple(sorted(unhealthy)),
    )
