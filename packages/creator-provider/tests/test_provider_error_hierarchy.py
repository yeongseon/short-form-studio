from __future__ import annotations

import os
from unittest import mock

import httpx
import pytest

from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError


@pytest.mark.asyncio
async def test_dalle_429_raises_rate_limit_error() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/images/generations")
    response = httpx.Response(429, request=request)
    status_error = httpx.HTTPStatusError("Rate limited", request=request, response=response)
    mock_response = mock.MagicMock()
    mock_response.raise_for_status.side_effect = status_error

    with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from creator_provider.image.dalle_provider import DalleProvider

        provider = DalleProvider(endpoint="https://api.openai.com", model_key="dall-e-3")
        with (
            mock.patch("httpx.AsyncClient.post", return_value=mock_response),
            pytest.raises(RateLimitError),
        ):
            await provider.generate("test")


@pytest.mark.asyncio
async def test_elevenlabs_timeout_raises_provider_timeout_error() -> None:
    request = httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/voice")
    connect_error = httpx.ConnectTimeout("timeout", request=request)

    with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "el-test"}):
        from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider

        provider = ElevenLabsProvider(
            endpoint="https://api.elevenlabs.io",
            model_key="elevenlabs-multilingual-v2",
        )
        with (
            mock.patch("httpx.AsyncClient.post", side_effect=connect_error),
            pytest.raises(ProviderTimeoutError),
        ):
            await provider.generate("hello")


@pytest.mark.asyncio
async def test_whisper_http_error_raises_provider_error_not_runtime_error(tmp_path) -> None:
    request = httpx.Request("POST", "http://stt:8200/transcribe")
    response = httpx.Response(500, request=request)
    status_error = httpx.HTTPStatusError("server", request=request, response=response)

    from creator_provider.stt.whisper_provider import WhisperSTTProvider

    source = tmp_path / "sample.wav"
    source.write_bytes(b"\x00" * 44)

    provider = WhisperSTTProvider(endpoint="http://stt:8200", model_key="whisper-small")
    with mock.patch("httpx.AsyncClient.post", side_effect=status_error):
        with pytest.raises(ProviderError):
            await provider.transcribe(str(source))
