from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import httpx
import pytest


class TestElevenLabsProvider:
    def test_constructor_sets_attributes(self):
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "el-test"}):
            from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider

            provider = ElevenLabsProvider(
                endpoint="https://api.elevenlabs.io",
                model_key="elevenlabs-multilingual-v2",
            )
            assert provider.endpoint == "https://api.elevenlabs.io"
            assert provider.model_key == "elevenlabs-multilingual-v2"
            assert provider.api_key == "el-test"

    def test_missing_api_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider

            with pytest.raises(ValueError, match="not configured"):
                ElevenLabsProvider(
                    endpoint="https://api.elevenlabs.io",
                    model_key="elevenlabs-multilingual-v2",
                )

    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path: Path):
        audio_bytes = b"a" * 32000

        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.content = audio_bytes

        output_path = tmp_path / "nested" / "elevenlabs.mp3"
        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "el-test"}):
            from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider

            provider = ElevenLabsProvider(
                endpoint="https://api.elevenlabs.io",
                model_key="elevenlabs-multilingual-v2",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
                result = await provider.generate(
                    "test text",
                    params={"output_path": str(output_path)},
                )

        mock_post.assert_called_once()
        assert output_path.exists()
        assert output_path.read_bytes() == audio_bytes
        assert result.audio_path == str(output_path)
        assert result.duration_seconds > 0
        assert result.model_key == "elevenlabs-multilingual-v2"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_runtime_error(self):
        request = httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/test")
        response = httpx.Response(401, request=request)
        status_error = httpx.HTTPStatusError("Unauthorized", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "el-test"}):
            from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider

            provider = ElevenLabsProvider(
                endpoint="https://api.elevenlabs.io",
                model_key="elevenlabs-multilingual-v2",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response), pytest.raises(RuntimeError, match="ElevenLabs API request failed"):
                await provider.generate("test text")

    @pytest.mark.asyncio
    async def test_generate_empty_response_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.content = b""

        with mock.patch.dict(os.environ, {"ELEVENLABS_API_KEY": "el-test"}):
            from creator_provider.tts.elevenlabs_provider import ElevenLabsProvider

            provider = ElevenLabsProvider(
                endpoint="https://api.elevenlabs.io",
                model_key="elevenlabs-multilingual-v2",
            )
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response), pytest.raises(RuntimeError, match="empty response"):
                await provider.generate("test text")


class TestOpenAITTSProvider:
    def test_constructor_sets_attributes(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.tts.openai_tts_provider import OpenAITTSProvider

            provider = OpenAITTSProvider(endpoint="https://api.openai.com", model_key="openai-tts-1")
            assert provider.endpoint == "https://api.openai.com"
            assert provider.model_key == "openai-tts-1"
            assert provider.api_key == "sk-test"

    def test_missing_api_key_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            from creator_provider.tts.openai_tts_provider import OpenAITTSProvider

            with pytest.raises(ValueError, match="not configured"):
                OpenAITTSProvider(endpoint="https://api.openai.com", model_key="openai-tts-1")

    @pytest.mark.asyncio
    async def test_generate_success(self, tmp_path: Path):
        audio_bytes = b"b" * 32000

        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.content = audio_bytes

        output_path = tmp_path / "nested" / "openai.mp3"
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.tts.openai_tts_provider import OpenAITTSProvider

            provider = OpenAITTSProvider(endpoint="https://api.openai.com", model_key="openai-tts-1")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response) as mock_post:
                result = await provider.generate(
                    "test text",
                    params={"output_path": str(output_path)},
                )

        mock_post.assert_called_once()
        assert output_path.exists()
        assert output_path.read_bytes() == audio_bytes
        assert result.audio_path == str(output_path)
        assert result.duration_seconds > 0
        assert result.model_key == "openai-tts-1"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises_runtime_error(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/audio/speech")
        response = httpx.Response(500, request=request)
        status_error = httpx.HTTPStatusError("Server error", request=request, response=response)

        mock_response = mock.MagicMock()
        mock_response.raise_for_status.side_effect = status_error

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.tts.openai_tts_provider import OpenAITTSProvider

            provider = OpenAITTSProvider(endpoint="https://api.openai.com", model_key="openai-tts-1")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response), pytest.raises(RuntimeError, match="OpenAI TTS API request failed"):
                await provider.generate("test text")

    @pytest.mark.asyncio
    async def test_generate_empty_response_raises(self):
        mock_response = mock.MagicMock()
        mock_response.raise_for_status = mock.MagicMock()
        mock_response.content = b""

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            from creator_provider.tts.openai_tts_provider import OpenAITTSProvider

            provider = OpenAITTSProvider(endpoint="https://api.openai.com", model_key="openai-tts-1")
            with mock.patch("httpx.AsyncClient.post", return_value=mock_response), pytest.raises(RuntimeError, match="empty response"):
                await provider.generate("test text")
