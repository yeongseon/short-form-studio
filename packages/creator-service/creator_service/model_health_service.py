"""Model health check service for monitoring model serving containers."""

import os
import time
from dataclasses import dataclass
from enum import Enum

import httpx
import anyio

from creator_service.provider_metadata import (
    KEYLESS_REMOTE_PROVIDERS, LOCAL_SERVICES, OFFLINE_PROVIDERS, REMOTE_CREDENTIALS,
)

_REMOTE_PROVIDERS = {value.health_key: value for value in REMOTE_CREDENTIALS.values()}


class ModelStatus(Enum):
    """Status of a model container."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    CONFIGURED = "configured"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
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
            service.health_key: os.getenv(service.env_var, service.default_endpoint)
            for service in LOCAL_SERVICES.values()
        }
        self.health_paths = {
            service.health_key: service.health_path for service in LOCAL_SERVICES.values()
        }

    async def check_model(
        self, model_name: str, *, endpoint: str | None = None,
    ) -> ModelHealthResult:
        """Check health of a single model provider.
        
        Args:
            model_name: Name of the model to check
            
        Returns:
            ModelHealthResult with health status and metadata
        """
        if model_name in OFFLINE_PROVIDERS | KEYLESS_REMOTE_PROVIDERS:
            return ModelHealthResult(
                model_name, model_name,
                ModelStatus.HEALTHY if model_name in OFFLINE_PROVIDERS else ModelStatus.UNKNOWN,
            )
        resolved_endpoint = endpoint if endpoint is not None else self.endpoints.get(model_name)
        if resolved_endpoint is None:
            credential = _REMOTE_PROVIDERS.get(model_name)
            if credential is None:
                return ModelHealthResult(
                    model_name=model_name,
                    endpoint="unknown",
                    status=ModelStatus.UNKNOWN,
                    error="Unknown model",
                )

            token = os.getenv(credential.env_var) or (
                os.getenv(credential.fallback_env_var) if credential.fallback_env_var else None
            )
            if token and token.strip():
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
        url = f"{resolved_endpoint.rstrip('/')}{health_path}"

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                response.raise_for_status()

            elapsed_ms = (time.perf_counter() - start) * 1000
            return ModelHealthResult(
                model_name=model_name,
                endpoint=resolved_endpoint,
                status=ModelStatus.HEALTHY,
                response_time_ms=elapsed_ms,
            )
        except httpx.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return ModelHealthResult(
                model_name=model_name,
                endpoint=resolved_endpoint,
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
        results: dict[str, ModelHealthResult] = {}

        async def check(name: str) -> None:
            results[name] = await self.check_model(name)

        async with anyio.create_task_group() as tasks:
            for name in provider_names:
                tasks.start_soon(check, name)
        return [results[name] for name in provider_names]
