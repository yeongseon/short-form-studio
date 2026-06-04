"""Tests for FFmpegService.render() resilience — temp file + ffprobe validation.

Covers:
- Non-zero exit + valid output → accepted (atomic rename)
- Non-zero exit + zero-byte file → rejected
- Non-zero exit + small corrupt file → rejected
- Non-zero exit + no file created → rejected
- Success (rc=0) → atomic rename to final path
- Stale output from previous run not accepted
- Timeout handling
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from creator_service.ffmpeg_service import FFmpegService, RenderInput
from creator_service.render_profile import RenderProfile


@pytest.fixture
def ffmpeg_service() -> FFmpegService:
    return FFmpegService(profile=RenderProfile.default())


@pytest.fixture
def render_input(tmp_path: Path) -> RenderInput:
    """Minimal RenderInput with a dummy image."""
    img = tmp_path / "scene.png"
    img.write_bytes(b"\x89PNG" + b"\x00" * 100)  # fake PNG header
    return RenderInput(
        image_paths=[img],
        audio_path=None,
        subtitle_path=None,
        scene_durations=[5.0],
    )


def _make_subprocess_result(returncode: int, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ffmpeg"], returncode=returncode, stdout="", stderr=stderr
    )


def _make_probe_result(duration: float) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ffprobe"], returncode=0, stdout=f"{duration}\n", stderr=""
    )


def _make_probe_failure() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["ffprobe"], returncode=1, stdout="", stderr="Invalid data"
    )


class TestRenderSuccess:
    """FFmpeg exits 0 — temp file renamed to final output."""

    def test_success_renames_temp_to_output(
        self, ffmpeg_service: FFmpegService, render_input: RenderInput, tmp_path: Path
    ):
        output_path = tmp_path / "output" / "video.mp4"
        tmp_file = output_path.with_suffix(".tmp.mp4")

        def fake_run(cmd, **kwargs):
            # Simulate FFmpeg writing to temp file (last arg in cmd)
            target = Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\x00" * 50_000)  # valid-sized file
            return _make_subprocess_result(0)

        with patch("creator_service.ffmpeg_service.subprocess.run", side_effect=fake_run):
            result = ffmpeg_service.render(render_input, output_path)

        assert result == output_path
        assert output_path.exists()
        assert not tmp_file.exists()  # temp file was renamed


class TestRenderNonZeroWithValidOutput:
    """FFmpeg exits non-zero but output is valid (verified by ffprobe)."""

    def test_accepts_valid_output_on_nonzero_exit(
        self, ffmpeg_service: FFmpegService, render_input: RenderInput, tmp_path: Path
    ):
        output_path = tmp_path / "output" / "video.mp4"

        call_count = {"n": 0}

        def fake_run(cmd, **kwargs):
            call_count["n"] += 1
            target = Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            if call_count["n"] == 1:
                # FFmpeg: write valid-sized file but exit non-zero
                target.write_bytes(b"\x00" * 50_000)
                return _make_subprocess_result(-12, "ENOMEM during filter cleanup")
            else:
                # ffprobe: return valid duration
                return _make_probe_result(30.0)

        with patch("creator_service.ffmpeg_service.subprocess.run", side_effect=fake_run):
            result = ffmpeg_service.render(render_input, output_path)

        assert result == output_path
        assert output_path.exists()
        assert output_path.stat().st_size == 50_000


class TestRenderNonZeroWithInvalidOutput:
    """FFmpeg exits non-zero and output is invalid — must raise."""

    def test_rejects_zero_byte_file(
        self, ffmpeg_service: FFmpegService, render_input: RenderInput, tmp_path: Path
    ):
        output_path = tmp_path / "output" / "video.mp4"

        def fake_run(cmd, **kwargs):
            target = Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")  # zero bytes
            return _make_subprocess_result(1, "Error")

        with patch("creator_service.ffmpeg_service.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="FFmpeg render failed"):
                ffmpeg_service.render(render_input, output_path)

        # Temp file should be cleaned up
        assert not output_path.with_suffix(".tmp.mp4").exists()

    def test_rejects_small_corrupt_file(
        self, ffmpeg_service: FFmpegService, render_input: RenderInput, tmp_path: Path
    ):
        output_path = tmp_path / "output" / "video.mp4"

        def fake_run(cmd, **kwargs):
            target = Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"corrupt" * 10)  # 70 bytes < 10KB min
            return _make_subprocess_result(1, "Error")

        with patch("creator_service.ffmpeg_service.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="FFmpeg render failed"):
                ffmpeg_service.render(render_input, output_path)

    def test_rejects_large_file_failing_ffprobe(
        self, ffmpeg_service: FFmpegService, render_input: RenderInput, tmp_path: Path
    ):
        """File > 10KB but ffprobe says it's not a valid video."""
        output_path = tmp_path / "output" / "video.mp4"

        call_count = {"n": 0}

        def fake_run(cmd, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # FFmpeg: write large file but exit non-zero
                target = Path(cmd[-1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"\x00" * 50_000)
                return _make_subprocess_result(1, "Segfault")
            else:
                # ffprobe: fails on the file
                return _make_probe_failure()

        with patch("creator_service.ffmpeg_service.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="FFmpeg render failed"):
                ffmpeg_service.render(render_input, output_path)

    def test_rejects_when_no_file_created(
        self, ffmpeg_service: FFmpegService, render_input: RenderInput, tmp_path: Path
    ):
        output_path = tmp_path / "output" / "video.mp4"

        def fake_run(cmd, **kwargs):
            # FFmpeg fails without creating any file
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            return _make_subprocess_result(1, "No such file or directory")

        with patch("creator_service.ffmpeg_service.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="FFmpeg render failed"):
                ffmpeg_service.render(render_input, output_path)


class TestRenderStaleOutput:
    """Previous output file must not be falsely accepted."""

    def test_stale_output_not_accepted(
        self, ffmpeg_service: FFmpegService, render_input: RenderInput, tmp_path: Path
    ):
        """Even if output_path exists from a previous run, it's not used."""
        output_path = tmp_path / "output" / "video.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"\x00" * 100_000)  # stale from previous run

        def fake_run(cmd, **kwargs):
            # FFmpeg fails, writes nothing to temp
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            return _make_subprocess_result(1, "Error")

        with patch("creator_service.ffmpeg_service.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="FFmpeg render failed"):
                ffmpeg_service.render(render_input, output_path)

        # The stale output_path should still exist (we only clean temp file)
        # But the render should NOT have accepted the stale file


class TestRenderTimeout:
    """subprocess.TimeoutExpired propagates correctly."""

    def test_timeout_raises(
        self, ffmpeg_service: FFmpegService, render_input: RenderInput, tmp_path: Path
    ):
        output_path = tmp_path / "output" / "video.mp4"

        def fake_run(cmd, **kwargs):
            Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=300)

        with patch("creator_service.ffmpeg_service.subprocess.run", side_effect=fake_run):
            with pytest.raises(subprocess.TimeoutExpired):
                ffmpeg_service.render(render_input, output_path)


class TestProbeOutputValid:
    """Unit tests for _probe_output_valid helper."""

    def test_valid_duration(self, ffmpeg_service: FFmpegService, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)

        with patch(
            "creator_service.ffmpeg_service.subprocess.run", return_value=_make_probe_result(45.5)
        ):
            assert ffmpeg_service._probe_output_valid(video) is True

    def test_zero_duration(self, ffmpeg_service: FFmpegService, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)

        with patch(
            "creator_service.ffmpeg_service.subprocess.run", return_value=_make_probe_result(0.0)
        ):
            assert ffmpeg_service._probe_output_valid(video) is False

    def test_probe_failure(self, ffmpeg_service: FFmpegService, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)

        with patch(
            "creator_service.ffmpeg_service.subprocess.run", return_value=_make_probe_failure()
        ):
            assert ffmpeg_service._probe_output_valid(video) is False

    def test_probe_timeout(self, ffmpeg_service: FFmpegService, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)

        with patch(
            "creator_service.ffmpeg_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=15),
        ):
            assert ffmpeg_service._probe_output_valid(video) is False

    def test_invalid_duration_string(self, ffmpeg_service: FFmpegService, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)

        result = subprocess.CompletedProcess(
            args=["ffprobe"], returncode=0, stdout="N/A\n", stderr=""
        )
        with patch("creator_service.ffmpeg_service.subprocess.run", return_value=result):
            assert ffmpeg_service._probe_output_valid(video) is False
