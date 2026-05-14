"""Unit tests for WhisperSTTProvider."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from creator_provider.stt.whisper_provider import WhisperSTTProvider


class TestWhisperSTTProviderInit(unittest.TestCase):
    def test_strips_trailing_slash(self) -> None:
        provider = WhisperSTTProvider(endpoint="http://stt:8200/", model_key="whisper-small")
        self.assertEqual(provider.endpoint, "http://stt:8200")

    def test_stores_model_key(self) -> None:
        provider = WhisperSTTProvider(endpoint="http://stt:8200", model_key="whisper-small")
        self.assertEqual(provider.model_key, "whisper-small")


class TestWhisperSTTProviderTranscribe(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    @patch("creator_provider.stt.whisper_provider.httpx.AsyncClient")
    def test_posts_to_transcribe_endpoint(self, mock_client_cls: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
            "text": "Hello",
            "language": "en",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = WhisperSTTProvider(endpoint="http://stt:8200", model_key="whisper-small")

        # Create a temp audio file for the test
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"\x00" * 44)
            audio_path = f.name

        self._run(provider.transcribe(audio_path))

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        self.assertEqual(call_args.args[0], "http://stt:8200/transcribe")

    @patch("creator_provider.stt.whisper_provider.httpx.AsyncClient")
    def test_returns_subtitle_result_with_segments_and_text(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "segments": [
                {"start": 0.0, "end": 1.5, "text": "Hello world"},
                {"start": 1.5, "end": 3.0, "text": "How are you"},
            ],
            "text": "Hello world How are you",
            "language": "en",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = WhisperSTTProvider(endpoint="http://stt:8200", model_key="whisper-small")

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"\x00" * 44)
            audio_path = f.name

        result = self._run(provider.transcribe(audio_path))

        self.assertEqual(result.model_key, "whisper-small")
        self.assertEqual(result.full_text, "Hello world How are you")
        self.assertEqual(len(result.segments), 2)

    @patch("creator_provider.stt.whisper_provider.httpx.AsyncClient")
    def test_sends_format_and_language_params(self, mock_client_cls: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"segments": [], "text": "", "language": "ko"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = WhisperSTTProvider(endpoint="http://stt:8200", model_key="whisper-small")

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"\x00" * 44)
            audio_path = f.name

        self._run(provider.transcribe(audio_path, params={"format": "vtt", "language": "ko"}))

        call_args = mock_client.post.call_args
        data = call_args.kwargs.get("data") or {}
        self.assertEqual(data.get("format"), "vtt")
        self.assertEqual(data.get("language"), "ko")

    @patch("creator_provider.stt.whisper_provider.httpx.AsyncClient")
    def test_filters_unallowlisted_params_and_logs_warning(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"segments": [], "text": "", "language": "en"}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = WhisperSTTProvider(endpoint="http://stt:8200", model_key="whisper-small")

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"\x00" * 44)
            audio_path = f.name

        with patch("creator_provider.stt.whisper_provider.logger.warning") as mock_warning:
            self._run(provider.transcribe(audio_path, params={"task": "transcribe", "bad": "x"}))

        call_args = mock_client.post.call_args
        data = call_args.kwargs.get("data") or {}
        self.assertEqual(data.get("task"), "transcribe")
        self.assertNotIn("bad", data)
        mock_warning.assert_called_once()

    @patch("creator_provider.stt.whisper_provider.httpx.AsyncClient")
    def test_http_error_raises_runtime_error(self, mock_client_cls: MagicMock) -> None:
        import httpx

        mock_client = AsyncMock()
        request = httpx.Request("POST", "http://stt:8200/transcribe")
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused", request=request)
        )
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = WhisperSTTProvider(endpoint="http://stt:8200", model_key="whisper-small")

        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"\x00" * 44)
            audio_path = f.name

        with self.assertRaises(RuntimeError) as ctx:
            self._run(provider.transcribe(audio_path))

        self.assertIn("Whisper STT provider", str(ctx.exception))
        self.assertIn("/transcribe", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
