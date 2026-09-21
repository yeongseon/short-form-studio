"""Tests for ASS subtitle conversion and brace escaping."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from creator_service.ffmpeg_service import FFmpegService


@pytest.fixture
def ffmpeg():
    return FFmpegService()


class TestSrtToAssConversion:
    """Test SRT to ASS subtitle conversion."""

    def _make_srt(self, tmp_path: Path, content: str) -> Path:
        srt = tmp_path / "test.srt"
        srt.write_text(content, encoding="utf-8")
        return srt

    def test_basic_conversion(self, ffmpeg, tmp_path):
        srt_content = (
            "1\n"
            "00:00:01,000 --> 00:00:03,000\n"
            "Hello world\n"
            "\n"
            "2\n"
            "00:00:04,000 --> 00:00:06,000\n"
            "Second line\n"
        )
        srt = self._make_srt(tmp_path, srt_content)
        ass_path = tmp_path / "test.ass"

        result = ffmpeg.convert_srt_to_ass(str(srt), str(ass_path))
        assert result.exists()

        content = result.read_text(encoding="utf-8")
        assert "[Script Info]" in content
        assert "Dialogue:" in content
        assert "Hello world" in content
        assert "Second line" in content

    def test_brace_escaping(self, ffmpeg, tmp_path):
        """Braces in subtitle text must be escaped to prevent ASS override injection."""
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\n{\\b1}Injected bold{\\b0}\n"
        srt = self._make_srt(tmp_path, srt_content)
        ass_path = tmp_path / "test.ass"

        result = ffmpeg.convert_srt_to_ass(str(srt), str(ass_path))
        content = result.read_text(encoding="utf-8")

        # Braces should be escaped as fullwidth characters
        assert "{" not in content.split("Dialogue:")[1]
        assert "}" not in content.split("Dialogue:")[1]
        # Original text intent preserved (as escaped)
        assert "\\b1" in content or "uff5b" in repr(content)

    def test_multiline_subtitle(self, ffmpeg, tmp_path):
        srt_content = "1\n00:00:01,000 --> 00:00:03,000\nLine one\nLine two\n"
        srt = self._make_srt(tmp_path, srt_content)
        ass_path = tmp_path / "test.ass"

        result = ffmpeg.convert_srt_to_ass(str(srt), str(ass_path))
        content = result.read_text(encoding="utf-8")

        # Multi-line should use ASS newline \\N
        assert "\\N" in content

    def test_empty_srt(self, ffmpeg, tmp_path):
        srt = self._make_srt(tmp_path, "")
        ass_path = tmp_path / "test.ass"

        result = ffmpeg.convert_srt_to_ass(str(srt), str(ass_path))
        content = result.read_text(encoding="utf-8")

        assert "[Script Info]" in content
        # No Dialogue lines
        assert "Dialogue:" not in content
