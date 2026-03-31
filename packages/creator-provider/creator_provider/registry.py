from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProviderCategory(Enum):
    LLM = "llm"
    IMAGE = "image"
    TTS = "tts"
    STT = "stt"


@dataclass
class ModelCatalogEntry:
    model_key: str
    provider_type: str
    endpoint: str
    category: ProviderCategory
    requires_gpu: bool = True
    is_local: bool = True
    default_params: dict[str, Any] | None = None


class ProviderRegistry:
    def __init__(self):
        self._catalog: dict[str, ModelCatalogEntry] = {}
        self._providers: dict[str, Any] = {}

    def register_model(self, entry: ModelCatalogEntry) -> None:
        self._catalog[entry.model_key] = entry

    def register_provider(self, provider_type: str, provider_class: type) -> None:
        self._providers[provider_type] = provider_class

    def resolve(self, model_key: str) -> ModelCatalogEntry:
        if model_key not in self._catalog:
            raise KeyError(f"Model '{model_key}' not found in catalog")
        return self._catalog[model_key]

    def get_provider(self, model_key: str) -> Any:
        entry = self.resolve(model_key)
        provider_class = self._providers.get(entry.provider_type)
        if provider_class is None:
            raise KeyError(f"Provider type '{entry.provider_type}' not registered")
        return provider_class(endpoint=entry.endpoint, model_key=model_key)

    def list_models(self, category: ProviderCategory | None = None) -> list[ModelCatalogEntry]:
        entries = list(self._catalog.values())
        if category:
            entries = [entry for entry in entries if entry.category == category]
        return entries

    @classmethod
    def create_default(cls) -> "ProviderRegistry":
        from creator_provider.image.dalle_provider import DalleProvider
        from creator_provider.image.imagen_provider import ImagenProvider
        from creator_provider.image.sd_local_provider import SDLocalProvider
        from creator_provider.image.stability_provider import StabilityProvider
        from creator_provider.llm.anthropic_provider import AnthropicProvider
        from creator_provider.llm.gemini_provider import GeminiProvider
        from creator_provider.llm.ollama_provider import OllamaProvider
        from creator_provider.llm.openai_provider import OpenAIProvider
        from creator_provider.stt.whisper_provider import WhisperSTTProvider
        from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider
        from creator_provider.tts.openai_tts_provider import OpenAITTSProvider
        from creator_provider.tts.qwen_tts_provider import QwenTTSProvider

        registry = cls()
        registry.register_provider("ollama", OllamaProvider)
        registry.register_provider("sd_local", SDLocalProvider)
        registry.register_provider("qwen_tts", QwenTTSProvider)
        registry.register_provider("elevenlabs_tts", ElevenLabsProvider)
        registry.register_provider("openai_tts", OpenAITTSProvider)
        registry.register_provider("whisper", WhisperSTTProvider)
        registry.register_provider("openai_llm", OpenAIProvider)
        registry.register_provider("anthropic_llm", AnthropicProvider)
        registry.register_provider("gemini_llm", GeminiProvider)
        registry.register_provider("openai_image", DalleProvider)
        registry.register_provider("stability_image", StabilityProvider)
        registry.register_provider("google_image", ImagenProvider)
        registry.register_model(
            ModelCatalogEntry(
                model_key="qwen3-4b",
                provider_type="ollama",
                endpoint="http://ollama:11434",
                category=ProviderCategory.LLM,
                requires_gpu=True,
                is_local=True,
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="sd15",
                provider_type="sd_local",
                endpoint="http://stable-diffusion:7860",
                category=ProviderCategory.IMAGE,
                requires_gpu=True,
                is_local=True,
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="qwen3-tts",
                provider_type="qwen_tts",
                endpoint="http://tts-qwen3:8100",
                category=ProviderCategory.TTS,
                requires_gpu=True,
                is_local=True,
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="elevenlabs-multilingual-v2",
                provider_type="elevenlabs_tts",
                endpoint="https://api.elevenlabs.io",
                category=ProviderCategory.TTS,
                requires_gpu=False,
                is_local=False,
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="openai-tts-1",
                provider_type="openai_tts",
                endpoint="https://api.openai.com",
                category=ProviderCategory.TTS,
                requires_gpu=False,
                is_local=False,
                default_params={"voice": "alloy"},
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="whisper-small",
                provider_type="whisper",
                endpoint="http://stt-whisper:8200",
                category=ProviderCategory.STT,
                requires_gpu=True,
                is_local=True,
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="gpt-4o-mini",
                provider_type="openai_llm",
                endpoint="https://api.openai.com",
                category=ProviderCategory.LLM,
                requires_gpu=False,
                is_local=False,
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="claude-sonnet-4-20250514",
                provider_type="anthropic_llm",
                endpoint="https://api.anthropic.com",
                category=ProviderCategory.LLM,
                requires_gpu=False,
                is_local=False,
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="gemini-2.0-flash",
                provider_type="gemini_llm",
                endpoint="https://generativelanguage.googleapis.com",
                category=ProviderCategory.LLM,
                requires_gpu=False,
                is_local=False,
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="dall-e-3",
                provider_type="openai_image",
                endpoint="https://api.openai.com",
                category=ProviderCategory.IMAGE,
                requires_gpu=False,
                is_local=False,
                default_params={"width": 1024, "height": 1792},
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="sd3-medium",
                provider_type="stability_image",
                endpoint="https://api.stability.ai",
                category=ProviderCategory.IMAGE,
                requires_gpu=False,
                is_local=False,
                default_params={"aspect_ratio": "9:16"},
            )
        )
        registry.register_model(
            ModelCatalogEntry(
                model_key="imagen-3",
                provider_type="google_image",
                endpoint="https://generativelanguage.googleapis.com",
                category=ProviderCategory.IMAGE,
                requires_gpu=False,
                is_local=False,
                default_params={"width": 1024, "height": 1792},
            )
        )
        return registry
