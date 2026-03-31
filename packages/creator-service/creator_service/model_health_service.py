"""Model health check service for monitoring model serving containers."""

from dataclasses import dataclass
from enum import Enum
import os


class ModelStatus(Enum):
    """Status of a model container."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
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
    """Check health of model serving containers."""
    
    def __init__(self):
        """Initialize health service with model endpoints from environment variables."""
        self.endpoints = {
            "ollama": os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
            "stable-diffusion": os.getenv("STABLE_DIFFUSION_BASE_URL", "http://stable-diffusion:7860"),
            "tts-piper": os.getenv("TTS_PIPER_BASE_URL", "http://tts-piper:5000"),
            "stt-whisper": os.getenv("STT_WHISPER_BASE_URL", "http://stt-whisper:9000"),
        }
        self.health_paths = {
            "ollama": "/api/tags",
            "stable-diffusion": "/sdapi/v1/options",
            "tts-piper": "/api/health",
            "stt-whisper": "/",  # placeholder — update when STT health endpoint is known
        }

    async def check_model(self, model_name: str) -> ModelHealthResult:
        """Check health of a single model container.
        
        Args:
            model_name: Name of the model to check
            
        Returns:
            ModelHealthResult with health status and metadata
        """
        endpoint = self.endpoints.get(model_name)
        if not endpoint:
            return ModelHealthResult(
                model_name=model_name,
                endpoint="unknown",
                status=ModelStatus.UNKNOWN,
                error="Unknown model"
            )
        
        health_path = self.health_paths.get(model_name, "/")
        url = f"{endpoint}{health_path}"
        
        # TODO: Implement actual HTTP call using httpx
        # In production: async with httpx.AsyncClient() as client: ...
        # For now, return placeholder result
        return ModelHealthResult(
            model_name=model_name,
            endpoint=endpoint,
            status=ModelStatus.UNKNOWN,
            error="Health check not yet implemented"
        )

    async def check_all(self) -> list[ModelHealthResult]:
        """Check health of all model containers.
        
        Returns:
            List of ModelHealthResult for each model container
        """
        results = []
        for name in self.endpoints:
            result = await self.check_model(name)
            results.append(result)
        return results
