"""Request-scoped health facts shared by catalog and setup read models."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import anyio
from creator_domain.provider_catalog import ModelCatalogEntry, ModelRegistry as ModelRegistry

from creator_service.model_health_service import ModelHealthResult, ModelStatus
from creator_service.provider_metadata import (
    KEYLESS_REMOTE_PROVIDERS,
    LOCAL_SERVICES,
    OFFLINE_PROVIDERS,
    PROVIDER_ALIASES,
    REMOTE_CREDENTIALS,
)


class HealthReader(Protocol):
    async def check_model(
        self, model_name: str, *, endpoint: str | None = None,
    ) -> ModelHealthResult: ...


@dataclass(frozen=True, slots=True)
class ProviderFact:
    entry: ModelCatalogEntry
    provider: str
    health_key: str
    is_local: bool
    keyless: bool
    status: ModelStatus


async def resolve_provider_facts(
    entries: Sequence[ModelCatalogEntry], health_service: HealthReader,
) -> tuple[ProviderFact, ...]:
    """Deduplicate probes by service identity and full endpoint, never hostname alone."""
    probes: dict[tuple[str, str | None], ModelStatus] = {}
    identities: list[tuple[str, str | None]] = []
    providers = [PROVIDER_ALIASES.get(entry.provider_type, entry.provider_type) for entry in entries]
    for entry, provider in zip(entries, providers, strict=True):
        local = LOCAL_SERVICES.get(provider)
        credential = REMOTE_CREDENTIALS.get(provider)
        if local is not None:
            endpoint = entry.endpoint.rstrip("/")
            identity = (local.health_key, endpoint)
        elif credential is not None:
            identity = (credential.health_key, None)
        else:
            identity = (provider, None)
        identities.append(identity)

    async def probe(identity: tuple[str, str | None]) -> None:
        key, endpoint = identity
        if key in OFFLINE_PROVIDERS:
            probes[identity] = ModelStatus.HEALTHY
        elif key not in {c.health_key for c in REMOTE_CREDENTIALS.values()} and endpoint is None:
            probes[identity] = ModelStatus.UNKNOWN
        else:
            result = (
                await health_service.check_model(key)
                if endpoint is None
                else await health_service.check_model(key, endpoint=endpoint)
            )
            probes[identity] = result.status

    async with anyio.create_task_group() as tasks:
        for identity in dict.fromkeys(identities):
            tasks.start_soon(probe, identity)

    return tuple(
        ProviderFact(
            entry=entry,
            provider=provider,
            health_key=identity[0],
            is_local=entry.is_local and provider not in KEYLESS_REMOTE_PROVIDERS,
            keyless=provider in OFFLINE_PROVIDERS | KEYLESS_REMOTE_PROVIDERS,
            status=probes[identity],
        )
        for entry, provider, identity in zip(entries, providers, identities, strict=True)
    )
