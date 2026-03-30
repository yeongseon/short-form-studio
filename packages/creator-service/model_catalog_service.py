"""Model catalog service backed by provider registry and health checks."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

try:
    from .model_health_service import ModelHealthService, ModelStatus
except ImportError:
    from model_health_service import ModelHealthService, ModelStatus


class ModelCatalogService:
    """Expose registry-backed model catalog and provider status."""

    _CATEGORY_TO_REGISTRY_VALUE = {
        "script": "llm",
        "image": "image",
        "tts": "tts",
        "stt": "stt",
    }

    _CATEGORY_TO_RESPONSE_KEY = {
        "llm": "script_models",
        "image": "image_models",
        "tts": "tts_models",
        "stt": "stt_models",
    }

    _HEALTH_TO_CATALOG_STATUS = {
        ModelStatus.HEALTHY: "available",
        ModelStatus.UNHEALTHY: "unavailable",
        ModelStatus.UNKNOWN: "unknown",
    }

    def __init__(self, registry: Any, health_service: ModelHealthService):
        self.registry = registry
        self.health_service = health_service

    async def list_models(self, category: str | None = None) -> dict[str, list[dict[str, object]]]:
        """List catalog models grouped by API response category keys."""
        response: dict[str, list[dict[str, object]]] = {
            "script_models": [],
            "image_models": [],
            "tts_models": [],
            "stt_models": [],
        }

        category_value = None
        if category is not None:
            category_value = self._CATEGORY_TO_REGISTRY_VALUE.get(category)
            if category_value is None:
                raise ValueError(f"Unsupported category '{category}'")

        entries = self.registry.list_models()
        for entry in entries:
            entry_category = entry.category.value
            if category_value is not None and entry_category != category_value:
                continue

            response_key = self._CATEGORY_TO_RESPONSE_KEY[entry_category]
            response[response_key].append(await self._catalog_entry(entry))

        return response

    async def get_status(self) -> dict[str, object]:
        """Return provider-level health and current GPU lock defaults."""
        providers: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()

        for entry in self.registry.list_models():
            provider_id = (entry.provider_type, entry.endpoint)
            if provider_id in seen:
                continue
            seen.add(provider_id)

            health_key = self._health_key(entry)
            health_result = await self.health_service.check_model(health_key)
            providers.append(
                {
                    "name": entry.provider_type,
                    "endpoint": entry.endpoint,
                    "healthy": health_result.status == ModelStatus.HEALTHY,
                    "loaded_model": None,
                    "gpu_locked": False,
                }
            )

        return {
            "providers": providers,
            "gpu_lock": {
                "active": False,
                "holder": None,
                "ttl_remaining": None,
            },
        }

    async def _catalog_entry(self, entry: Any) -> dict[str, object]:
        health_result = await self.health_service.check_model(self._health_key(entry))
        return {
            "key": entry.model_key,
            "label": self._format_label(entry.model_key, entry.is_local),
            "provider_type": entry.provider_type,
            "is_local": entry.is_local,
            "requires_gpu": entry.requires_gpu,
            "status": self._HEALTH_TO_CATALOG_STATUS[health_result.status],
        }

    @staticmethod
    def _format_label(model_key: str, is_local: bool) -> str:
        words = []
        for token in model_key.replace("_", "-").split("-"):
            if not token:
                continue
            if token[:-1].isdigit() and token[-1:].isalpha():
                words.append(f"{token[:-1]}{token[-1:].upper()}")
            else:
                words.append(token[:1].upper() + token[1:])

        location = "Local" if is_local else "Remote"
        return f"{' '.join(words)} ({location})"

    @staticmethod
    def _health_key(entry: Any) -> str:
        parsed = urlparse(entry.endpoint)
        if parsed.hostname:
            return parsed.hostname
        return entry.provider_type
