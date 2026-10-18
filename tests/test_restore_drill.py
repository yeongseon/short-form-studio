from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_drill.py"
sys.path.insert(0, str(SCRIPT.parent))
from restore_drill import render_restored_timeline
from restore_drill_runtime import DrillError, validate_release_manifest


def test_disposable_restore_drill() -> None:
    # Given
    if shutil.which("docker") is None:
        pytest.skip("docker is required for the disposable restore drill")

    # When
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )
    print(result.stdout, end="")

    # Then
    assert result.returncode == 0, result.stderr
    assert "RESTORE DRILL PASSED" in result.stdout
    assert "provider calls: 0" in result.stdout
    assert "production schema: migrated" in result.stdout
    assert "real API auth: owner=200 workspace-b=404 revoked=401 missing=401 timeline=200/404" in result.stdout
    assert "real API downloads: media=200 final-mp4=200 foreign=404 revoked=401 missing=401 checksum=verified ffprobe=verified" in result.stdout
    assert "post-restore render: restored Timeline image audio -> final.mp4" in result.stdout
    assert "provider guard: armed and untouched" in result.stdout
    assert "broker recovery: pending=failed queued=queued running=failed" in result.stdout
    evidence_line = next(
        line for line in result.stdout.splitlines() if line.startswith("RESTORE_EVIDENCE=")
    )
    evidence = json.loads(evidence_line.removeprefix("RESTORE_EVIDENCE="))
    assert evidence["restore_head_sha"] == os.environ["RESTORE_HEAD_SHA"]
    assert all("@sha256:" in digest for digest in evidence["release_image_digests"])
    assert evidence["credential_free"] is True
    assert evidence["phase_durations_seconds"]["total"] > 0
    assert evidence["restored_timeline_segments"] > 0
    assert evidence["registered_artifact"]["size_bytes"] > 0
    assert len(evidence["registered_artifact"]["checksum"]) == 64


def test_render_uses_restored_timeline_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / "image.png").write_bytes(b"image")
    (restored / "audio.wav").write_bytes(b"audio")
    commands: list[tuple[str, ...]] = []

    def record_docker(*arguments: str) -> subprocess.CompletedProcess[str]:
        commands.append(arguments)
        (restored / "final.mp4").write_bytes(b"rendered")
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("restore_drill.docker", record_docker)
    timeline = [
        {"asset_id": 601, "duration_seconds": 1}
    ]

    # When
    render_restored_timeline(restored, timeline, {601: "image.png"})

    # Then
    command = commands[0]
    assert "/media/image.png" in command
    assert "/media/audio.wav" in command
    assert (restored / "final.mp4").read_bytes() == b"rendered"


@pytest.mark.parametrize("digest", ["a" * 64, "b" * 64, "c" * 64])
def test_release_manifest_rejects_placeholder_digest(
    tmp_path: Path, digest: str
) -> None:
    # Given
    manifest = tmp_path / "release.json"
    manifest.write_text(
        json.dumps({"api": f"registry/api@sha256:{digest}", "worker": "registry/worker@sha256:" + "d" * 64, "web": "registry/web@sha256:" + "e" * 64})
    )

    # When / Then
    with pytest.raises(DrillError, match="placeholder"):
        validate_release_manifest(manifest)
