"""Model catalog service backed by provider registry and health checks."""

from __future__ import annotations

from creator_service.model_health_service import ModelStatus
from creator_service.provider_facts import (
    HealthReader, ModelRegistry, ProviderFact, resolve_provider_facts,
)


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
        ModelStatus.CONFIGURED: "configured_unverified",
        ModelStatus.UNHEALTHY: "unavailable",
        ModelStatus.UNKNOWN: "unknown",
    }

    # Explicit labels for known model keys.  New models that lack an entry
    # fall through to the generic _format_label_fallback() formatter.
    _KNOWN_LABELS: dict[str, str] = {
        "qwen3-4b": "Qwen3 4B",
        "qwen3-8b": "Qwen3 8B",
        "sd15": "Stable Diffusion 1.5",
        "sd-2.1": "Stable Diffusion 2.1",
        "qwen3-tts": "Qwen3 TTS",
        "elevenlabs-multilingual-v2": "ElevenLabs Multilingual v2",
        "openai-tts-1": "OpenAI TTS-1",
        "whisper-small": "Whisper Small",
        "gpt-4o-mini": "GPT-4o Mini",
        "claude-sonnet-4-20250514": "Claude Sonnet",
        "gemini-2.0-flash": "Gemini 2.0 Flash",
        "dall-e-3": "DALL-E 3",
        "sd3-medium": "Stability SD3",
        "imagen-3": "Imagen 3",
        "llama-3.1-8b": "Llama 3.1 8B",
    }

    def __init__(self, registry: ModelRegistry, health_service: HealthReader):
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

        entries = [entry for entry in self.registry.list_models()
                   if category_value is None or entry.category.value == category_value]
        for fact in await resolve_provider_facts(entries, self.health_service):
            response_key = self._CATEGORY_TO_RESPONSE_KEY[fact.entry.category.value]
            response[response_key].append(self._catalog_entry(fact))

        return response

    async def get_status(self) -> dict[str, object]:
        """Return provider-level health and current GPU lock defaults."""
        providers: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()

        for fact in await resolve_provider_facts(self.registry.list_models(), self.health_service):
            provider_id = (fact.health_key, fact.entry.endpoint if fact.is_local else "")
            if provider_id in seen:
                continue
            seen.add(provider_id)

            providers.append(
                {
                    "name": fact.health_key,
                    "healthy": fact.status is ModelStatus.HEALTHY,
                    "status": self._HEALTH_TO_CATALOG_STATUS[fact.status],
                }
            )

        return {
            "providers": providers,
            "gpu_lock": {"active": False},
        }

    def _catalog_entry(self, fact: ProviderFact) -> dict[str, object]:
        entry = fact.entry
        return {
            "key": entry.model_key,
            "label": self._format_label(entry.model_key, fact.is_local),
            "provider_type": entry.provider_type,
            "is_local": fact.is_local,
            "requires_gpu": entry.requires_gpu,
            "status": self._HEALTH_TO_CATALOG_STATUS[fact.status],
            "default_params": entry.default_params or {},
        }

    def _format_label(self, model_key: str, is_local: bool) -> str:
        known = self._KNOWN_LABELS.get(model_key)
        base = known if known is not None else self._format_label_fallback(model_key)
        location = "Local" if is_local else "Remote"
        return f"{base} ({location})"

    @staticmethod
    def _format_label_fallback(model_key: str) -> str:
        """Best-effort title-case for unknown model keys."""
        return model_key.replace("-", " ").replace("_", " ").title()
