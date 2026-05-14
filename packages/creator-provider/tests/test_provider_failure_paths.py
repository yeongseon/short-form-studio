"""Provider adapter failure path tests — Ollama, SD Local, Piper TTS.

Covers:
- Connection refused / timeout → ProviderTimeoutError
- HTTP 429 → RateLimitError
- HTTP 500 → ProviderError
- Empty/malformed response bodies
- Prompt validation rejection → ProviderValidationError
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from creator_provider.exceptions import (
    ProviderError,
    ProviderTimeoutError,
    ProviderValidationError,
    RateLimitError,
)
from creator_provider.llm.ollama_provider import OllamaProvider
from creator_provider.image.sd_local_provider import SDLocalProvider
from creator_provider.tts.piper_tts_provider import PiperTTSProvider


# ---------------------------------------------------------------------------
# Ollama LLM Provider
# ---------------------------------------------------------------------------


class TestOllamaFailurePaths:
    @pytest.fixture
    def provider(self):
        return OllamaProvider(endpoint="http://localhost:11434", model_key="qwen3-4b")

    @pytest.mark.asyncio
    async def test_connection_refused(self, provider: OllamaProvider):
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
            with pytest.raises(ProviderTimeoutError, match="Connection refused"):
                await provider.generate("Hello")

    @pytest.mark.asyncio
    async def test_timeout(self, provider: OllamaProvider):
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("read timeout")):
            with pytest.raises(ProviderTimeoutError, match="read timeout"):
                await provider.generate("Hello")

    @pytest.mark.asyncio
    async def test_http_429_rate_limit(self, provider: OllamaProvider):
        mock_response = httpx.Response(429, request=httpx.Request("POST", "http://test"))
        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.HTTPStatusError(
                "429", request=mock_response.request, response=mock_response
            ),
        ):
            with pytest.raises(RateLimitError):
                await provider.generate("Hello")

    @pytest.mark.asyncio
    async def test_http_500_server_error(self, provider: OllamaProvider):
        mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test"))
        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.HTTPStatusError(
                "500", request=mock_response.request, response=mock_response
            ),
        ):
            with pytest.raises(ProviderError):
                await provider.generate("Hello")

    @pytest.mark.asyncio
    async def test_empty_content_response(self, provider: OllamaProvider):
        mock_response = httpx.Response(
            200, json={"message": {"content": ""}}, request=httpx.Request("POST", "http://test")
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(ProviderError, match="empty content"):
                await provider.generate("Hello")

    @pytest.mark.asyncio
    async def test_missing_message_field(self, provider: OllamaProvider):
        mock_response = httpx.Response(
            200, json={"status": "ok"}, request=httpx.Request("POST", "http://test")
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(ProviderError, match="empty content"):
                await provider.generate("Hello")

    @pytest.mark.asyncio
    async def test_prompt_too_long(self, provider: OllamaProvider):
        long_prompt = "x" * 40_000
        with pytest.raises(ValueError, match="too long"):
            await provider.generate(long_prompt)


# ---------------------------------------------------------------------------
# SD Local Image Provider
# ---------------------------------------------------------------------------


class TestSDLocalFailurePaths:
    @pytest.fixture
    def provider(self):
        return SDLocalProvider(endpoint="http://localhost:7860", model_key="sd-1.5")

    @pytest.mark.asyncio
    async def test_connection_refused(self, provider: SDLocalProvider):
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
            with pytest.raises(ProviderTimeoutError, match="Connection refused"):
                await provider.generate("a cat")

    @pytest.mark.asyncio
    async def test_timeout(self, provider: SDLocalProvider):
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("GPU timeout")):
            with pytest.raises(ProviderTimeoutError, match="GPU timeout"):
                await provider.generate("a cat")

    @pytest.mark.asyncio
    async def test_http_500(self, provider: SDLocalProvider):
        mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test"))
        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.HTTPStatusError(
                "500", request=mock_response.request, response=mock_response
            ),
        ):
            with pytest.raises(ProviderError):
                await provider.generate("a cat")

    @pytest.mark.asyncio
    async def test_empty_images_response(self, provider: SDLocalProvider):
        mock_response = httpx.Response(
            200, json={"images": []}, request=httpx.Request("POST", "http://test")
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            with pytest.raises(ProviderError, match="no images"):
                await provider.generate("a cat")

    @pytest.mark.asyncio
    async def test_prompt_too_long(self, provider: SDLocalProvider):
        long_prompt = "x" * 3000
        with pytest.raises(ValueError, match="too long"):
            await provider.generate(long_prompt)


# ---------------------------------------------------------------------------
# Piper TTS Provider
# ---------------------------------------------------------------------------


class TestPiperTTSFailurePaths:
    @pytest.fixture
    def provider(self):
        return PiperTTSProvider(endpoint="http://localhost:8100", model_key="piper")

    @pytest.mark.asyncio
    async def test_connection_refused(self, provider: PiperTTSProvider):
        with patch("httpx.AsyncClient.post", side_effect=httpx.ConnectError("Connection refused")):
            with pytest.raises(ProviderTimeoutError, match="Connection refused"):
                await provider.generate("Hello world")

    @pytest.mark.asyncio
    async def test_timeout(self, provider: PiperTTSProvider):
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("TTS timeout")):
            with pytest.raises(ProviderTimeoutError, match="TTS timeout"):
                await provider.generate("Hello world")

    @pytest.mark.asyncio
    async def test_http_500(self, provider: PiperTTSProvider):
        mock_response = httpx.Response(500, request=httpx.Request("POST", "http://test"))
        with patch(
            "httpx.AsyncClient.post",
            side_effect=httpx.HTTPStatusError(
                "500", request=mock_response.request, response=mock_response
            ),
        ):
            with pytest.raises(ProviderError):
                await provider.generate("Hello world")

    @pytest.mark.asyncio
    async def test_short_audio_returns_zero_duration(self, provider: PiperTTSProvider):
        """WAV data too short to parse → duration = 0."""
        short_bytes = b"\x00" * 10
        mock_response = httpx.Response(
            200, content=short_bytes, request=httpx.Request("POST", "http://test")
        )
        with patch("httpx.AsyncClient.post", return_value=mock_response):
            result = await provider.generate("Hello")
            assert result.duration_seconds == 0.0

    @pytest.mark.asyncio
    async def test_prompt_too_long(self, provider: PiperTTSProvider):
        long_text = "x" * 6000
        with pytest.raises(ValueError, match="too long"):
            await provider.generate(long_text)
