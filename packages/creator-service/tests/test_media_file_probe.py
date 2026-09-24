from pathlib import Path
import subprocess

import pytest
from PIL import Image
from creator_service.media_probe import probe_media_metadata
from creator_service.media_upload_validation import MediaUploadRejected


@pytest.mark.parametrize("kind,suffix", [("image", ".png"), ("video", ".mp4"), ("audio", ".wav")])
def test_probe_accepts_real_file_without_materializing_bytes(tmp_path: Path, kind: str, suffix: str) -> None:
    # Given actual media on disk (no full-file bytes fixture).
    path = tmp_path / f"media{suffix}"
    if kind == "image":
        Image.new("RGB", (16, 24)).save(path)
    else:
        source = "color=c=blue:s=16x24:d=0.2" if kind == "video" else "sine=duration=0.2"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", source, str(path)], check=True)
    # When probing the path directly.
    result = probe_media_metadata(path, kind=kind)
    # Then actual media properties and file size are returned.
    assert result.size_bytes == path.stat().st_size
    assert result.mime_type == {"image": "image/png", "video": "video/mp4", "audio": "audio/wav"}[kind]
    if kind != "audio":
        assert (result.width, result.height) == (16, 24)
    if kind != "image":
        assert result.duration_seconds == pytest.approx(0.2, abs=0.05)


def test_probe_rejects_invalid_file(tmp_path: Path) -> None:
    # Given fake video bytes, regardless of extension.
    path = tmp_path / "fake.mp4"
    path.write_bytes(b"not media")
    # When probing the actual file.
    with pytest.raises(MediaUploadRejected):
        probe_media_metadata(path, kind="video")
    # Then ownership remains with the caller.
    assert path.exists()
