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
from restore_drill import render_restored_timeline, stop_process
from restore_drill_runtime import RuntimeFixture
from restore_drill_runtime import DrillError, seed_production_fixture, validate_release_manifest


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


def test_render_invokes_production_timeline_worker_with_restored_database_and_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    restored = tmp_path / "restored"
    restored.mkdir()
    commands: list[tuple[tuple[str, ...], Path | None, dict[str, str] | None]] = []

    def record_run(
        *arguments: str, cwd: Path | None = None, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        commands.append((arguments, cwd, env))
        (restored / "final.mp4").write_bytes(b"rendered")
        return subprocess.CompletedProcess(
            arguments, 0, '{"count": 2, "artifact_id": 702}\n', ""
        )

    monkeypatch.setattr("restore_drill.run", record_run)
    fixture = RuntimeFixture("owner", "foreign", "revoked", 201, 401, 501, 601, 701)

    # When
    count, updated_fixture, evidence = render_restored_timeline(
        "postgresql://restore:test@127.0.0.1:5432/restore", restored, fixture
    )

    # Then
    command, cwd, environment = commands[0]
    assert command[:2] == (sys.executable, "-c")
    assert "render_saved_timeline" in command[2]
    assert "RenderLayers(audio=artifact_root / 'audio.wav')" in command[2]
    assert cwd == SCRIPT.parents[1] / "apps/worker-orchestrator"
    assert environment is not None
    assert environment["DATABASE_URL"].startswith("postgresql://restore:")
    assert environment["ARTIFACT_ROOT"] == str(restored)
    assert count == 2
    assert updated_fixture.artifact_id == 702
    assert evidence["size_bytes"] == len(b"rendered")
    assert (restored / "final.mp4").read_bytes() == b"rendered"


def test_fixture_seeds_production_safe_restored_asset_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    media = tmp_path / "media"
    media.mkdir()
    (media / "image.png").write_bytes(b"image")
    (media / "final.mp4").write_bytes(b"video")
    commands: list[tuple[str, ...]] = []

    def record_docker(*arguments: str) -> subprocess.CompletedProcess[str]:
        commands.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr("restore_drill_runtime.docker", record_docker)

    # When
    seed_production_fixture("source", media)

    # Then
    sql = commands[0][-1]
    assert "workspaces/201/assets/image.png" in sql


def test_stop_process_kills_child_that_ignores_termination() -> None:
    # Given
    class StuckProcess:
        def __init__(self) -> None:
            self.terminated = False
            self.killed = False
            self.waits = 0

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.killed = True

        def wait(self, timeout: float) -> int:
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("guard", timeout)
            return 0

    process = StuckProcess()

    # When
    stop_process(process)

    # Then
    assert process.terminated is True
    assert process.killed is True
    assert process.waits == 2


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
