from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from creator_service.media_asset_service import (
    MediaUploadRejected,
    ProbeResult,
    probe_media_metadata,
)
from PIL import Image


def _png_bytes(width: int = 12, height: int = 20) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_bytes(width: int = 9, height: int = 7) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (5, 5, 5)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _video_bytes(seconds: float = 1.0, width: int = 32, height: int = 24) -> bytes:
    if shutil.which("ffmpeg") is None:  # pragma: no cover - env guard
        pytest.skip("ffmpeg not available")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "v.mp4"
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi",
            "-i", f"color=c=blue:s={width}x{height}:d={seconds}",
            "-pix_fmt", "yuv420p",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0 or not out.exists():  # pragma: no cover - env guard
            pytest.skip("ffmpeg could not produce a test video")
        return out.read_bytes()


def _audio_bytes(seconds: float = 1.0) -> bytes:
    if shutil.which("ffmpeg") is None:  # pragma: no cover - env guard
        pytest.skip("ffmpeg not available")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a.mp3"
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={seconds}",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0 or not out.exists():  # pragma: no cover - env guard
            pytest.skip("ffmpeg could not produce a test audio file")
        return out.read_bytes()


# --- image ------------------------------------------------------------------


def test_probe_image_returns_dimensions_mime_and_size() -> None:
    data = _png_bytes(width=12, height=20)
    result = probe_media_metadata(data, kind="image")

    assert isinstance(result, ProbeResult)
    assert result.width == 12
    assert result.height == 20
    assert result.duration_seconds is None
    assert result.mime_type == "image/png"
    assert result.size_bytes == len(data)


def test_probe_image_detects_jpeg_mime() -> None:
    result = probe_media_metadata(_jpeg_bytes(), kind="image")
    assert result.mime_type == "image/jpeg"


def test_probe_image_rejects_corrupt_bytes() -> None:
    with pytest.raises(MediaUploadRejected):
        probe_media_metadata(b"not-an-image", kind="image")


def test_probe_rejects_empty_payload() -> None:
    with pytest.raises(MediaUploadRejected):
        probe_media_metadata(b"", kind="image")


# --- video ------------------------------------------------------------------


def test_probe_video_returns_dimensions_duration_mime_size() -> None:
    data = _video_bytes(seconds=1.0, width=32, height=24)
    result = probe_media_metadata(data, kind="video")

    assert result.width == 32
    assert result.height == 24
    assert result.duration_seconds is not None and result.duration_seconds > 0
    assert result.mime_type == "video/mp4"
    assert result.size_bytes == len(data)


def test_probe_video_rejects_corrupt_bytes() -> None:
    with pytest.raises(MediaUploadRejected):
        probe_media_metadata(b"not-a-video", kind="video")


# --- audio ------------------------------------------------------------------


def test_probe_audio_returns_duration_mime_size_no_dimensions() -> None:
    data = _audio_bytes(seconds=1.0)
    result = probe_media_metadata(data, kind="audio")

    assert result.width is None
    assert result.height is None
    assert result.duration_seconds is not None and result.duration_seconds > 0
    assert result.mime_type in {"audio/mpeg", "audio/mp3"}
    assert result.size_bytes == len(data)


def test_probe_audio_rejects_corrupt_bytes() -> None:
    with pytest.raises(MediaUploadRejected):
        probe_media_metadata(b"not-audio", kind="audio")


# --- resource bounds & robustness -------------------------------------------


def test_probe_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        probe_media_metadata(_png_bytes(), kind="hologram")


def test_probe_rejects_oversized_payload() -> None:
    with pytest.raises(MediaUploadRejected):
        probe_media_metadata(_png_bytes(), kind="image", max_bytes=5)


def test_probe_ffprobe_timeout_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _video_bytes()

    def _raise_timeout(*args: object, **kwargs: object):
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=1)

    monkeypatch.setattr(
        "creator_service.media_asset_service.subprocess.run", _raise_timeout
    )
    with pytest.raises(MediaUploadRejected):
        probe_media_metadata(data, kind="video")


def test_probe_uses_argument_list_not_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    real_run = subprocess.run

    def _spy_run(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        captured["shell"] = kwargs.get("shell", False)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(
        "creator_service.media_asset_service.subprocess.run", _spy_run
    )
    probe_media_metadata(_video_bytes(), kind="video")

    assert isinstance(captured["cmd"], list)
    assert captured["shell"] is False
    assert captured["cmd"][0] == "ffprobe"


def test_probe_cleans_up_temp_files(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[str] = []
    import creator_service.media_asset_service as mod

    real_tempdir = tempfile.TemporaryDirectory

    class _TrackingTempDir(real_tempdir):  # type: ignore[misc]
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            created.append(self.name)

    monkeypatch.setattr(mod.tempfile, "TemporaryDirectory", _TrackingTempDir)
    probe_media_metadata(_video_bytes(), kind="video")

    assert created, "expected a temp directory to be used for probing"
    for path in created:
        assert not Path(path).exists(), f"temp dir not cleaned up: {path}"
