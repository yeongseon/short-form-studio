# ADR-005: Provider Abstraction for AI Services

**Status**: Accepted  
**Date**: 2026-05-12  
**Decision makers**: @yeongseon

## Context

The platform integrates 20+ AI models across four categories (LLM, Image, TTS, STT) from multiple vendors (OpenAI, Anthropic, Google, Stability AI, ElevenLabs, local Ollama, etc.). Without a unified abstraction, each service method would need vendor-specific code, making it impossible to swap providers or add new ones without modifying business logic.

## Decision

**Define abstract base classes (ports) in `creator-provider/base.py` and implement one concrete provider per vendor/model.**

### Port interfaces

```python
class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, params: dict | None = None) -> str: ...

class ImageProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, params: dict | None = None) -> ImageResult: ...

class TTSProvider(ABC):
    @abstractmethod
    async def generate(self, text: str, voice: str = "default", params: dict | None = None) -> AudioResult: ...

class STTProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: str, params: dict | None = None) -> SubtitleResult: ...
```

### Typed result dataclasses

Each provider returns a typed result (`ImageResult`, `AudioResult`, `SubtitleResult`) containing the artifact path, metadata, and the `model_key` that produced it — enabling traceability.

### Provider registry

`ProviderRegistry` is a central catalog that maps `model_key` strings to provider instances:

```python
registry = ProviderRegistry.create_default()
provider = registry.get_provider("openai/gpt-4o-mini")  # → OpenAIProvider instance
provider = registry.get_provider("stability/sd3")       # → StabilityProvider instance
```

- `ProviderCategory` enum: `LLM`, `IMAGE`, `TTS`, `STT`
- `ModelCatalogEntry`: metadata per model (category, display name, requires API key, etc.)
- `create_default()`: factory that registers all available providers based on configured API keys
- Singleton via `get_default_registry()` for runtime use

### Exception hierarchy

```
ProviderError (RuntimeError)
├── ProviderTimeoutError    — upstream API timeout
├── RateLimitError          — 429 / quota exhausted
├── ProviderValidationError — invalid input (prompt too long, bad params)
└── ProviderAuthError       — invalid or missing API key
```

Services catch `ProviderError` uniformly regardless of which vendor threw it.

### Concrete implementations (current)

| Category | Providers |
|---|---|
| LLM | OpenAI, Anthropic, Gemini, Ollama, Groq |
| Image | DALL-E, Stability, Imagen, Pollinations, SD Local, Codex, HuggingFace, Groq SVG, Placeholder |
| TTS | ElevenLabs, OpenAI TTS, Qwen TTS, CosyVoice, Piper, Edge TTS |
| STT | Whisper, Groq STT |

## Consequences

- Adding a new provider = one file implementing the ABC + registry entry. Zero business logic changes.
- Business logic (services, tasks) depend only on `LLMProvider`/`ImageProvider`/etc. — never on concrete classes.
- `creator-provider` depends on `creator-domain` only (per ADR-001). Services do NOT import provider internals.
- Providers are independently testable — each has unit tests with mocked HTTP responses.
- The `model_key` selection is a user-facing choice (stored per run), making provider selection a runtime decision.
