"""P2-7 (V7): guard against registry-vs-health endpoint drift.

Every LOCAL registry provider whose endpoint is a real host URL (not the keyless
"local" sentinel) must have a matching ModelHealthService.endpoints entry, so its
health lookup key resolves to a probe instead of silently returning UNKNOWN.
tts-cosyvoice was missing this entry.
"""

from urllib.parse import urlparse

from creator_provider.registry import get_default_registry
from creator_service.model_health_service import ModelHealthService


def _local_host_providers() -> dict[str, str]:
    """Map local providers with a real host endpoint to that hostname."""
    result: dict[str, str] = {}
    for entry in get_default_registry().list_models():
        if not entry.is_local:
            continue
        parsed = urlparse(entry.endpoint)
        if parsed.hostname:
            result[entry.provider_type] = parsed.hostname
    return result


def test_cosyvoice_has_a_health_endpoint() -> None:
    service = ModelHealthService()
    assert "tts-cosyvoice" in service.endpoints
    assert "tts-cosyvoice" in service.health_paths


def test_every_local_host_provider_has_a_health_endpoint() -> None:
    service = ModelHealthService()
    missing = [
        f"{provider_type} (host {host})"
        for provider_type, host in _local_host_providers().items()
        if host not in service.endpoints
    ]
    assert not missing, f"local providers missing a health endpoint: {missing}"


def test_every_health_endpoint_has_a_health_path() -> None:
    service = ModelHealthService()
    missing = [name for name in service.endpoints if name not in service.health_paths]
    assert not missing, f"health endpoints missing a probe path: {missing}"
