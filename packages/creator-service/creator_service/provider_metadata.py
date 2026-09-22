from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class RemoteCredential:
    label: str
    env_var: str
    health_key: str
    fallback_env_var: str | None = None
    optional: bool = False


REMOTE_CREDENTIALS = MappingProxyType({
    "openai": RemoteCredential("OpenAI", "OPENAI_API_KEY", "api.openai.com"),
    "anthropic": RemoteCredential("Anthropic", "ANTHROPIC_API_KEY", "api.anthropic.com"),
    "google": RemoteCredential("Google (Gemini / Imagen)", "GOOGLE_API_KEY", "generativelanguage.googleapis.com"),
    "stability": RemoteCredential("Stability AI", "STABILITY_API_KEY", "api.stability.ai"),
    "elevenlabs": RemoteCredential("ElevenLabs", "ELEVENLABS_API_KEY", "api.elevenlabs.io"),
    "groq": RemoteCredential("Groq", "GROQ_API_KEY", "api.groq.com"),
    "huggingface_image": RemoteCredential(
        "Hugging Face", "HF_TOKEN", "router.huggingface.co", "HUGGINGFACE_TOKEN", True,
    ),
})

PROVIDER_ALIASES = MappingProxyType({
    "openai_llm": "openai", "openai_image": "openai", "openai_tts": "openai",
    "anthropic_llm": "anthropic", "gemini_llm": "google", "google_image": "google",
    "stability_image": "stability", "elevenlabs_tts": "elevenlabs",
    "groq_llm": "groq", "groq_stt": "groq", "groq_svg_image": "groq",
})


@dataclass(frozen=True, slots=True)
class LocalService:
    health_key: str
    env_var: str
    default_endpoint: str
    health_path: str


LOCAL_SERVICES = MappingProxyType({
    "ollama": LocalService("ollama", "OLLAMA_BASE_URL", "http://ollama:11434", "/api/tags"),
    "sd_local": LocalService("stable-diffusion", "STABLE_DIFFUSION_BASE_URL", "http://stable-diffusion:7860", "/sdapi/v1/options"),
    "qwen_tts": LocalService("tts-qwen3", "TTS_QWEN3_BASE_URL", "http://tts-qwen3:8100", "/health"),
    "cosyvoice_tts": LocalService("tts-cosyvoice", "TTS_COSYVOICE_BASE_URL", "http://tts-cosyvoice:50000", "/health"),
    "whisper": LocalService("stt-whisper", "STT_WHISPER_BASE_URL", "http://stt-whisper:8200", "/health"),
})

OFFLINE_PROVIDERS = frozenset({"placeholder_image"})
KEYLESS_REMOTE_PROVIDERS = frozenset({"edge_tts", "pollinations_image"}) | frozenset(
    provider for provider, credential in REMOTE_CREDENTIALS.items() if credential.optional
)
UNSUPPORTED_REMOTE_PROVIDERS = MappingProxyType({
    "codex_image": "Unsupported private Codex backend; SDK-managed file authentication and availability are unknown",
})
