"""Unit tests for CosyVoiceProvider."""

from __future__ import annotations

import asyncio
import struct
import tempfile
import unittest
from importlib import import_module
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from creator_provider.tts.cosyvoice_provider import (
    CosyVoiceProvider,
    _wav_duration_seconds,
)


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


class TestCosyVoiceProviderInit(unittest.TestCase):
    def test_strips_trailing_slash(self) -> None:
        provider = CosyVoiceProvider(endpoint="http://tts:50000/", model_key="cosyvoice-0.5b")
        self.assertEqual(provider.endpoint, "http://tts:50000")

    def test_stores_model_key(self) -> None:
        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")
        self.assertEqual(provider.model_key, "cosyvoice-0.5b")


class TestCosyVoiceProviderInstruct(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_posts_to_instruct_endpoint(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes()
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")
        with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
            self._run(
                provider.generate(
                    "안녕하세요", voice="default", params={"output_path": "/tmp/test.wav"}
                )
            )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        self.assertIn("/inference_instruct", url)

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_instruct_payload_has_required_fields(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes()
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")
        with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
            self._run(
                provider.generate(
                    "테스트 텍스트",
                    voice="korean_narrator",
                    params={
                        "instruct_text": "Speak with dramatic emphasis",
                        "speed": 1.2,
                        "output_path": "/tmp/out.wav",
                    },
                )
            )

        payload = (
            mock_client.post.call_args.kwargs.get("json") or mock_client.post.call_args.args[1]
        )
        self.assertEqual(payload["tts_text"], "테스트 텍스트")
        self.assertEqual(payload["instruct_text"], "Speak with dramatic emphasis")
        self.assertEqual(payload["speed"], 1.2)
        self.assertEqual(payload["speaker_id"], "korean_narrator")

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_returns_audio_result_with_correct_model_key(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes(sample_rate=22050, data_size=44100)
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")
        with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
            result = self._run(provider.generate("Hi", params={"output_path": "/tmp/test.wav"}))

        self.assertEqual(result.model_key, "cosyvoice-0.5b")
        self.assertEqual(result.audio_path, "/tmp/test.wav")
        self.assertGreater(result.duration_seconds, 0.0)

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_sft_mode_posts_to_sft_endpoint(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes()
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")
        with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
            self._run(
                provider.generate(
                    "SFT mode test",
                    params={"mode": "sft", "speaker": "中文男", "output_path": "/tmp/sft.wav"},
                )
            )

        call_args = mock_client.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        self.assertIn("/inference_sft", url)
        payload = call_args.kwargs.get("json") or call_args.args[1]
        self.assertEqual(payload["speaker_id"], "中文男")

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_zero_shot_requires_reference_audio(self, mock_client_cls: MagicMock) -> None:
        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")
        from creator_provider.exceptions import ProviderError

        with self.assertRaises(ProviderError) as ctx:
            with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
                self._run(
                    provider.generate(
                        "test", params={"mode": "zero_shot", "output_path": "/tmp/x.wav"}
                    )
                )
        self.assertIn("reference_audio", str(ctx.exception))

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_zero_shot_reference_file_not_found(self, mock_client_cls: MagicMock) -> None:
        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")
        from creator_provider.exceptions import ProviderError

        with self.assertRaises(ProviderError) as ctx:
            with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
                self._run(
                    provider.generate(
                        "test",
                        params={
                            "mode": "zero_shot",
                            "reference_audio": "/tmp/nonexistent_ref.wav",
                            "output_path": "/tmp/x.wav",
                        },
                    )
                )
        self.assertIn("not found", str(ctx.exception))

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_zero_shot_with_valid_reference(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes()
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")

        # Create a temporary reference audio file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_file:
            ref_file.write(_make_wav_bytes())
            ref_path = ref_file.name

        try:
            with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
                result = self._run(
                    provider.generate(
                        "Clone voice test",
                        params={
                            "mode": "zero_shot",
                            "reference_audio": ref_path,
                            "reference_text": "Reference transcript",
                            "output_path": "/tmp/clone.wav",
                        },
                    )
                )
            self.assertEqual(result.model_key, "cosyvoice-0.5b")
            # Verify multipart upload was used
            call_args = mock_client.post.call_args
            self.assertIn("files", call_args.kwargs)
        finally:
            Path(ref_path).unlink(missing_ok=True)


class TestCosyVoiceProviderErrors(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_connection_error_maps_to_timeout_error(self, mock_client_cls: MagicMock) -> None:
        import httpx
        from creator_provider.exceptions import ProviderTimeoutError

        mock_client = AsyncMock()
        request = httpx.Request("POST", "http://tts:50000/inference_instruct")
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused", request=request)
        )
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")

        with self.assertRaises(ProviderTimeoutError):
            with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
                self._run(provider.generate("test", params={"output_path": "/tmp/x.wav"}))

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_empty_audio_raises_provider_error(self, mock_client_cls: MagicMock) -> None:
        from creator_provider.exceptions import ProviderError

        mock_response = MagicMock()
        mock_response.content = b"tiny"  # < 100 bytes
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")

        with self.assertRaises(ProviderError) as ctx:
            with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp"}):
                self._run(provider.generate("test", params={"output_path": "/tmp/x.wav"}))
        self.assertIn("empty or invalid", str(ctx.exception))

    @patch("creator_provider.tts.cosyvoice_provider.httpx.AsyncClient")
    def test_rejects_path_traversal(self, mock_client_cls: MagicMock) -> None:
        wav = _make_wav_bytes()
        mock_response = MagicMock()
        mock_response.content = wav
        mock_response.raise_for_status = MagicMock()
        unsafe_path_component = import_module("creator_domain.sanitize").UnsafePathComponent

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_ctx

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")

        with patch.dict("os.environ", {"ARTIFACT_ROOT": "/tmp/artifacts"}):
            bad_paths = (
                "../../etc/passwd",
                "data/artifacts/../../../etc/passwd",
                "/tmp/evil.wav",
            )
            for bad_path in bad_paths:
                with self.assertRaisesRegex(unsafe_path_component, "escapes artifact root"):
                    self._run(provider.generate("Hi", params={"output_path": bad_path}))

    def test_validates_text_length(self) -> None:
        from creator_provider.exceptions import ProviderValidationError

        provider = CosyVoiceProvider(endpoint="http://tts:50000", model_key="cosyvoice-0.5b")
        long_text = "x" * 100_001  # MAX_TTS_TEXT_CHARS is typically exceeded

        with self.assertRaises(ProviderValidationError):
            self._run(provider.generate(long_text, params={"output_path": "/tmp/x.wav"}))


class TestCosyVoiceWavDuration(unittest.TestCase):
    def test_valid_wav_header(self) -> None:
        wav = _make_wav_bytes(
            sample_rate=22050, num_channels=1, bits_per_sample=16, data_size=44100
        )
        duration = _wav_duration_seconds(wav)
        self.assertAlmostEqual(duration, 1.0, places=2)

    def test_short_bytes_returns_zero(self) -> None:
        self.assertEqual(_wav_duration_seconds(b"short"), 0.0)

    def test_zero_sample_rate_returns_zero(self) -> None:
        wav = _make_wav_bytes(sample_rate=0)
        self.assertEqual(_wav_duration_seconds(wav), 0.0)

    def test_stereo_wav(self) -> None:
        wav = _make_wav_bytes(
            sample_rate=44100, num_channels=2, bits_per_sample=16, data_size=176400
        )
        duration = _wav_duration_seconds(wav)
        self.assertAlmostEqual(duration, 1.0, places=2)


class TestCosyVoiceRegistration(unittest.TestCase):
    def test_cosyvoice_registered_in_catalog(self) -> None:
        from creator_provider.registry import ProviderCategory, get_default_registry

        registry = get_default_registry()
        entry = registry.resolve("cosyvoice-0.5b")
        self.assertEqual(entry.provider_type, "cosyvoice_tts")
        self.assertEqual(entry.category, ProviderCategory.TTS)
        self.assertTrue(entry.requires_gpu)
        self.assertTrue(entry.is_local)

    def test_cosyvoice_provider_instantiates(self) -> None:
        from creator_provider.registry import get_default_registry

        registry = get_default_registry()
        provider = registry.get_provider("cosyvoice-0.5b")
        self.assertIsInstance(provider, CosyVoiceProvider)
        self.assertIn("50000", provider.endpoint)


if __name__ == "__main__":
    unittest.main()
