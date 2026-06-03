"""Tests for Phase 4 free provider implementations and bug fixes."""

from __future__ import annotations

import os
import struct
import tempfile
import zlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- PlaceholderImageProvider Tests ---


class TestPlaceholderImageProvider:
    """Tests for packages/creator-provider/creator_provider/image/placeholder_provider.py"""

    @pytest.fixture
    def provider(self):
        from creator_provider.image.placeholder_provider import PlaceholderImageProvider

        return PlaceholderImageProvider(endpoint="", model_key="placeholder")

    @pytest.mark.asyncio
    async def test_generates_valid_png(self, provider, tmp_path):
        output = tmp_path / "test.png"
        with patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            result = await provider.generate("test prompt", params={"output_path": str(output)})
        assert output.exists()
        data = output.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert result.model_key == "placeholder"

    @pytest.mark.asyncio
    async def test_bounds_width_height(self, provider, tmp_path):
        output = tmp_path / "test.png"
        with patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            result = await provider.generate(
                "test", params={"output_path": str(output), "width": 99999, "height": -5}
            )
        assert result.width == 4096
        assert result.height == 1

    @pytest.mark.asyncio
    async def test_deterministic_color(self, provider, tmp_path):
        """Same prompt produces same color (hashlib md5, not Python hash())."""
        out1 = tmp_path / "a.png"
        out2 = tmp_path / "b.png"
        with patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            await provider.generate(
                "same prompt", params={"output_path": str(out1), "width": 1, "height": 1}
            )
            await provider.generate(
                "same prompt", params={"output_path": str(out2), "width": 1, "height": 1}
            )
        assert out1.read_bytes() == out2.read_bytes()

    @pytest.mark.asyncio
    async def test_default_dimensions(self, provider, tmp_path):
        output = tmp_path / "test.png"
        with patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            result = await provider.generate("test", params={"output_path": str(output)})
        assert result.width == 1024
        assert result.height == 1792

# --- EdgeTTSProvider Tests ---


class TestEdgeTTSProvider:
    """Tests for packages/creator-provider/creator_provider/tts/edge_tts_provider.py"""

    @pytest.fixture
    def provider(self):
        from creator_provider.tts.edge_tts_provider import EdgeTTSProvider

        return EdgeTTSProvider(endpoint="", model_key="edge-tts")

    @pytest.mark.asyncio
    async def test_connection_error_raises_timeout(self, provider, tmp_path):
        """ConnectionError should raise ProviderTimeoutError (retryable)."""
        from creator_provider.exceptions import ProviderTimeoutError

        output = tmp_path / "audio.mp3"
        with patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            with patch("edge_tts.Communicate") as mock_comm:
                instance = MagicMock()
                instance.save = AsyncMock(side_effect=ConnectionError("network down"))
                mock_comm.return_value = instance
                with pytest.raises(ProviderTimeoutError):
                    await provider.generate("test text", params={"output_path": str(output)})

    @pytest.mark.asyncio
    async def test_generic_error_raises_provider_error(self, provider, tmp_path):
        """Non-connection errors should raise ProviderError (non-retryable)."""
        from creator_provider.exceptions import ProviderError

        output = tmp_path / "audio.mp3"
        with patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            with patch("edge_tts.Communicate") as mock_comm:
                instance = MagicMock()
                instance.save = AsyncMock(side_effect=RuntimeError("unknown"))
                mock_comm.return_value = instance
                with pytest.raises(ProviderError, match="Edge TTS generation failed"):
                    await provider.generate("test text", params={"output_path": str(output)})
    @pytest.mark.asyncio
    async def test_validates_text_length(self, provider, tmp_path):
        """Excessively long text should be rejected."""
        from creator_provider.validation import MAX_TTS_TEXT_CHARS

        output = tmp_path / "audio.mp3"
        with pytest.raises(Exception):  # ValidationError from validate_prompt_length
            await provider.generate(
                "x" * (MAX_TTS_TEXT_CHARS + 1), params={"output_path": str(output)}
            )


# --- GroqSTTProvider Tests ---


class TestGroqSTTProvider:
    """Tests for packages/creator-provider/creator_provider/stt/groq_stt_provider.py"""

    @pytest.fixture
    def provider(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            from creator_provider.stt.groq_stt_provider import GroqSTTProvider

            return GroqSTTProvider(
                endpoint="https://api.groq.com/openai/v1", model_key="groq-whisper-large-v3-turbo"
            )

    @pytest.mark.asyncio
    async def test_uses_model_key_not_hardcoded(self, provider, tmp_path):
        """Provider should use self.model_key, not a hardcoded model name."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"RIFF" + b"\x00" * 100)
        output_srt = tmp_path / "out.srt"

        with patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.json.return_value = {"text": "hello", "segments": []}
                mock_response.raise_for_status = MagicMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                await provider.transcribe(
                    str(audio_file), params={"output_path": str(output_srt)}
                )

                call_kwargs = mock_client.post.call_args
                form_data = (
                    call_kwargs.kwargs.get("data", {})
                    if call_kwargs.kwargs
                    else call_kwargs[1].get("data", {})
                )
                assert form_data["model"] == "groq-whisper-large-v3-turbo"

    @pytest.mark.asyncio
    async def test_format_param_writes_vtt(self, provider, tmp_path):
        """When params contains format='vtt', output should be WebVTT format."""
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"RIFF" + b"\x00" * 100)
        output_vtt = tmp_path / "out.vtt"

        with patch.dict(os.environ, {"ARTIFACT_ROOT": str(tmp_path)}):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.json.return_value = {
                    "text": "hello world",
                    "segments": [{"start": 0.0, "end": 1.0, "text": "hello world"}],
                }
                mock_response.raise_for_status = MagicMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                await provider.transcribe(
                    str(audio_file), params={"output_path": str(output_vtt), "format": "vtt"}
                )

        content = output_vtt.read_text()
        assert content.startswith("WEBVTT")

    @pytest.mark.asyncio
    async def test_http_error_raises_mapped_exception(self, provider, tmp_path):
        """HTTP errors should be mapped via map_httpx_error."""
        import httpx

        from creator_provider.exceptions import RateLimitError

        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"RIFF" + b"\x00" * 100)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            response_429 = httpx.Response(429, request=httpx.Request("POST", "http://test"))
            mock_client.post.side_effect = httpx.HTTPStatusError(
                "rate limited", request=httpx.Request("POST", "http://test"), response=response_429
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(RateLimitError):
                await provider.transcribe(str(audio_file))


# --- LocalStorageBackend same-file upload test ---


class TestLocalStorageSameFileUpload:
    """Test for the self-overwrite fix in object_storage.py"""

    def test_same_file_upload_does_not_truncate(self, tmp_path):
        """When source == destination, upload should return without truncating."""
        from creator_service.object_storage import LocalStorageBackend

        backend = LocalStorageBackend(root=str(tmp_path))

        test_file = tmp_path / "artifacts" / "1" / "audio" / "audio.wav"
        test_file.parent.mkdir(parents=True)
        test_file.write_bytes(b"audio content here" * 100)
        original_size = test_file.stat().st_size

        with open(test_file, "rb") as f:
            result = backend.upload("artifacts/1/audio/audio.wav", f, "audio/wav")

        assert test_file.stat().st_size == original_size
        assert result.key == "artifacts/1/audio/audio.wav"


# --- FFmpeg subtitle path escaping test ---


class TestSubtitlePathEscaping:
    """Test _escape_subtitle_path in ffmpeg_service.py"""

    def test_escapes_special_characters(self):
        from creator_service.ffmpeg_service import _escape_subtitle_path

        # Backslash
        assert "\\\\" in _escape_subtitle_path(Path("/path/with\\backslash.srt"))
        # Colon (on all platforms for FFmpeg filter syntax)
        assert "\\:" in _escape_subtitle_path(Path("/path/with:colon.srt"))
        # Single quote
        result = _escape_subtitle_path(Path("/path/with'quote.srt"))
        assert "\\'" in result or "'" not in result

    def test_normal_path_unchanged(self):
        from creator_service.ffmpeg_service import _escape_subtitle_path

        result = _escape_subtitle_path(Path("/simple/path/file.srt"))
        # Should still be valid (no unnecessary escaping beyond the function's spec)
        assert "file.srt" in result


# --- Render duration fallback test ---


class TestRenderDurationFallback:
    """Test that render uses audio duration when no paragraph audio exists."""

    def test_audio_duration_used_for_scene_durations(self, tmp_path):
        """When audio_path exists, scene_durations should use actual audio duration."""
        import sys
        from unittest.mock import patch as _patch

        sys.path.insert(0, "apps/worker-orchestrator")
        from tasks.render_video import compute_scene_durations

        from creator_service.ffmpeg_service import FFmpegService
        from creator_service.render_profile import RenderProfile

        profile = RenderProfile.default()
        ffmpeg = FFmpegService(profile=profile)

        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")

        with _patch.object(ffmpeg, "get_audio_duration", return_value=30.0):
            result = compute_scene_durations(ffmpeg, audio_file, 3, profile.max_duration_seconds)

        assert result == [10.0, 10.0, 10.0]
        assert result[0] != profile.max_duration_seconds / 3

    def test_fallback_to_max_duration_when_no_audio(self):
        """When no audio_path exists, should fall back to max_duration_seconds."""
        import sys

        sys.path.insert(0, "apps/worker-orchestrator")
        from tasks.render_video import compute_scene_durations

        from creator_service.ffmpeg_service import FFmpegService
        from creator_service.render_profile import RenderProfile

        profile = RenderProfile.default()
        ffmpeg = FFmpegService(profile=profile)

        result = compute_scene_durations(ffmpeg, None, 3, profile.max_duration_seconds)

        assert result == [profile.max_duration_seconds / 3] * 3
