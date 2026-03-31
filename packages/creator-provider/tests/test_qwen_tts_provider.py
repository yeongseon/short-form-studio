"""Unit tests for QwenTTSProvider."""

from __future__ import annotations

import asyncio
import struct
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from creator_provider.tts.qwen_tts_provider import QwenTTSProvider, _wav_duration_seconds


def _make_wav_bytes(
    num_channels: int = 1,
    sample_rate: int = 22050,
    bits_per_sample: int = 16,
    data_size: int = 44100,
) -> bytes:
    """Build a minimal WAV header (44 bytes) followed by zero audio data."""
    header = bytearray(44)
    header[0:4] = b"RIFF"
    header[22:24] = struct.pack("<H", num_channels)
    header[24:28] = struct.pack("<I", sample_rate)
    header[34:36] = struct.pack("<H", bits_per_sample)
    header[40:44] = struct.pack("<I", data_size)
    return bytes(header) + b"\x00" * data_size


class TestQwenTTSProviderInit(unittest.TestCase):
    def test_strips_trailing_slash(self) -> None:
        provider = QwenTTSProvider(endpoint="http://tts:8100/", model_key="qwen3-tts")
        self.assertEqual(provider.endpoint, "http://tts:8100")

    def test_stores_model_key(self) -> None:
        provider = QwenTTSProvider(endpoint="http://tts:8100", model_key="qwen3-tts")
        self.assertEqual(provider.model_key, "qwen3-tts")


class TestQwenTTSProviderGenerate(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    @patch("creator_provider.tts.qwen_tts_provider.httpx.AsyncClient")
    def test_posts_to_synthesize_endpoint(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes()
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = QwenTTSProvider(endpoint="http://tts:8100", model_key="qwen3-tts")
        result = self._run(provider.generate("Hello", voice="default", params={"output_path": "/tmp/test.wav"}))

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        self.assertEqual(call_args.args[0], "http://tts:8100/synthesize")

    @patch("creator_provider.tts.qwen_tts_provider.httpx.AsyncClient")
    def test_payload_contains_voice_id_language_speed(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes()
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = QwenTTSProvider(endpoint="http://tts:8100", model_key="qwen3-tts")
        self._run(provider.generate("Test text", voice="custom_voice", params={"language": "en", "speed": 1.5, "output_path": "/tmp/out.wav"}))

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args.args[1]
        self.assertEqual(payload["text"], "Test text")
        self.assertEqual(payload["voice_id"], "custom_voice")
        self.assertEqual(payload["language"], "en")
        self.assertEqual(payload["speed"], 1.5)

    @patch("creator_provider.tts.qwen_tts_provider.httpx.AsyncClient")
    def test_returns_audio_result_with_model_key(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes(sample_rate=22050, data_size=44100)
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = QwenTTSProvider(endpoint="http://tts:8100", model_key="qwen3-tts")
        result = self._run(provider.generate("Hi", params={"output_path": "/tmp/test.wav"}))

        self.assertEqual(result.model_key, "qwen3-tts")
        self.assertEqual(result.audio_path, "/tmp/test.wav")
        self.assertGreater(result.duration_seconds, 0.0)

    @patch("creator_provider.tts.qwen_tts_provider.httpx.AsyncClient")
    def test_http_error_raises_runtime_error(self, mock_client_cls: MagicMock) -> None:
        import httpx

        mock_client = AsyncMock()
        request = httpx.Request("POST", "http://tts:8100/synthesize")
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused", request=request))
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = QwenTTSProvider(endpoint="http://tts:8100", model_key="qwen3-tts")

        with self.assertRaises(RuntimeError) as ctx:
            self._run(provider.generate("test", params={"output_path": "/tmp/x.wav"}))

        self.assertIn("Qwen3 TTS provider", str(ctx.exception))
        self.assertIn("/synthesize", str(ctx.exception))

    @patch("creator_provider.tts.qwen_tts_provider.httpx.AsyncClient")
    def test_default_language_from_env(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes()
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = QwenTTSProvider(endpoint="http://tts:8100", model_key="qwen3-tts")

        with patch.dict("os.environ", {"TTS_DEFAULT_LANGUAGE": "en"}):
            self._run(provider.generate("Hi", params={"output_path": "/tmp/out.wav"}))

        payload = mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args.args[1]
        self.assertEqual(payload["language"], "en")


class TestWavDuration(unittest.TestCase):
    def test_valid_wav_header(self) -> None:
        wav = _make_wav_bytes(sample_rate=22050, num_channels=1, bits_per_sample=16, data_size=44100)
        duration = _wav_duration_seconds(wav)
        self.assertAlmostEqual(duration, 1.0, places=2)

    def test_short_bytes_returns_zero(self) -> None:
        self.assertEqual(_wav_duration_seconds(b"short"), 0.0)

    def test_zero_sample_rate_returns_zero(self) -> None:
        wav = _make_wav_bytes(sample_rate=0)
        self.assertEqual(_wav_duration_seconds(wav), 0.0)


if __name__ == "__main__":
    unittest.main()
