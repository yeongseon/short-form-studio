"""Model health check service for monitoring model serving containers."""

import asyncio
import os
import time
from dataclasses import dataclass
from enum import Enum

import httpx

_REMOTE_PROVIDERS: dict[str, str] = {
    "api.openai.com": "OPENAI_API_KEY",
    "api.anthropic.com": "ANTHROPIC_API_KEY",
    "generativelanguage.googleapis.com": "GOOGLE_API_KEY",
    "api.stability.ai": "STABILITY_API_KEY",
    "api.elevenlabs.io": "ELEVENLABS_API_KEY",
}


class ModelStatus(Enum):
    """Status of a model container."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CONFIGURED = "configured"
    UNKNOWN = "unknown"


@dataclass
class ModelHealthResult:
    """Result of a model health check."""
    model_name: str
    endpoint: str
    status: ModelStatus
    response_time_ms: float | None = None
    error: str | None = None


class ModelHealthService:
    """Check health of local and remote model providers."""
    
    def __init__(self):
        """Initialize health service with model endpoints from environment variables."""
        self.endpoints = {
            "ollama": os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            "stable-diffusion": os.getenv("STABLE_DIFFUSION_BASE_URL", "http://stable-diffusion:7860"),
            "tts-qwen3": os.getenv("TTS_QWEN3_BASE_URL", "http://tts-qwen3:8100"),
            "stt-whisper": os.getenv("STT_WHISPER_BASE_URL", "http://stt-whisper:8200"),
        }
        self.health_paths = {
            "ollama": "/api/tags",
            "stable-diffusion": "/sdapi/v1/options",
            "tts-qwen3": "/health",
            "stt-whisper": "/health",
        }

    async def check_model(self, model_name: str) -> ModelHealthResult:
        """Check health of a single model provider.
        
        Args:
            model_name: Name of the model to check
            
        Returns:
            ModelHealthResult with health status and metadata
        """
        endpoint = self.endpoints.get(model_name)
        if endpoint is None:
            api_key_env = _REMOTE_PROVIDERS.get(model_name)
            if api_key_env is None:
                return ModelHealthResult(
                    model_name=model_name,
                    endpoint="unknown",
                    status=ModelStatus.UNKNOWN,
                    error="Unknown model",
                )

            if os.getenv(api_key_env, "").strip():
                return ModelHealthResult(
                    model_name=model_name,
                    endpoint=model_name,
                    status=ModelStatus.CONFIGURED,
                )

            # Remote provider without API key: skip (not configured, not unhealthy)
            return ModelHealthResult(
                model_name=model_name,
                endpoint=model_name,
                status=ModelStatus.UNKNOWN,
                error="API key not configured (optional)",
            )
        
        health_path = self.health_paths.get(model_name, "/")
        url = f"{endpoint}{health_path}"

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                response.raise_for_status()

            elapsed_ms = (time.perf_counter() - start) * 1000
            return ModelHealthResult(
                model_name=model_name,
                endpoint=endpoint,
                status=ModelStatus.HEALTHY,
                response_time_ms=elapsed_ms,
            )
        except httpx.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ModelHealthResult(
                model_name=model_name,
                endpoint=endpoint,
                status=ModelStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error=str(exc),
            )

    async def check_all(self) -> list[ModelHealthResult]:
        """Check health of all model providers.
        
        Returns:
            List of ModelHealthResult for each model container
        """
        provider_names = [*self.endpoints, *_REMOTE_PROVIDERS]
        return await asyncio.gather(*(self.check_model(name) for name in provider_names))
