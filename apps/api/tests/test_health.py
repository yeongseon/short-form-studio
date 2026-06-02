"""Tests for health and healthz endpoints."""
from unittest.mock import AsyncMock, patch

import pytest
from creator_service.model_health_service import ModelHealthResult, ModelStatus


@pytest.mark.asyncio
async def test_healthz_returns_ok(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_returns_ok_when_all_healthy(client):
    mock_results = [
        ModelHealthResult(
            model_name="ollama",
            endpoint="http://ollama:11434",
            status=ModelStatus.HEALTHY,
            response_time_ms=12.3,
            error=None,
        ),
        ModelHealthResult(
            model_name="stable-diffusion",
            endpoint="http://stable-diffusion:7860",
            status=ModelStatus.HEALTHY,
            response_time_ms=45.6,
            error=None,
        ),
    ]
    with patch("shorts_api.main.model_health") as mock_health:
        mock_health.check_all = AsyncMock(return_value=mock_results)
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    # Endpoint and error are stripped from the public response
    assert body == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_returns_degraded_when_model_unhealthy(client):
    mock_results = [
        ModelHealthResult(
            model_name="ollama",
            endpoint="http://ollama:11434",
            status=ModelStatus.HEALTHY,
            response_time_ms=10.0,
            error=None,
        ),
        ModelHealthResult(
            model_name="stable-diffusion",
            endpoint="http://stable-diffusion:7860",
            status=ModelStatus.UNHEALTHY,
            response_time_ms=5000.0,
            error="Connection refused",
        ),
    ]
    with patch("shorts_api.main.model_health") as mock_health:
        mock_health.check_all = AsyncMock(return_value=mock_results)
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    # models detail not exposed without admin key
    assert "models" not in body
