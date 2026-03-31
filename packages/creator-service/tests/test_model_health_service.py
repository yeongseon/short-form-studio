from unittest.mock import AsyncMock, patch

import httpx
import pytest

from creator_service.model_health_service import ModelHealthService, ModelStatus


@pytest.fixture
def health_service() -> ModelHealthService:
    return ModelHealthService()


@pytest.mark.asyncio
async def test_local_provider_healthy(health_service: ModelHealthService) -> None:
    response = httpx.Response(200, request=httpx.Request("GET", "http://ollama:11434/api/tags"))
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_client

    with patch("creator_service.model_health_service.httpx.AsyncClient", return_value=mock_context):
        result = await health_service.check_model("ollama")

    assert result.status == ModelStatus.HEALTHY
    assert result.endpoint == "http://ollama:11434"
    assert result.error is None


@pytest.mark.asyncio
async def test_local_provider_unhealthy_on_http_error(health_service: ModelHealthService) -> None:
    request = httpx.Request("GET", "http://ollama:11434/api/tags")
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection failed", request=request))
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_client

    with patch("creator_service.model_health_service.httpx.AsyncClient", return_value=mock_context):
        result = await health_service.check_model("ollama")

    assert result.status == ModelStatus.UNHEALTHY
    assert result.endpoint == "http://ollama:11434"
    assert result.error is not None


@pytest.mark.asyncio
async def test_remote_provider_healthy_when_api_key_configured(
    health_service: ModelHealthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    result = await health_service.check_model("api.openai.com")

    assert result.status == ModelStatus.HEALTHY
    assert result.endpoint == "api.openai.com"
    assert result.error is None


@pytest.mark.asyncio
async def test_remote_provider_unhealthy_when_api_key_missing(
    health_service: ModelHealthService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = await health_service.check_model("api.openai.com")

    assert result.status == ModelStatus.UNHEALTHY
    assert result.endpoint == "api.openai.com"
    assert result.error == "API key not configured"


@pytest.mark.asyncio
async def test_unknown_provider_returns_unknown(health_service: ModelHealthService) -> None:
    result = await health_service.check_model("unknown-provider")

    assert result.status == ModelStatus.UNKNOWN
    assert result.endpoint == "unknown"
    assert result.error == "Unknown model"
