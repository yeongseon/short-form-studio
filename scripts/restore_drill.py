#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install the API requirements and PostgreSQL client tools.
# 2. Run: python scripts/restore_drill.py
# 3. The drill creates and removes only disposable Docker containers.
# ──────────────────

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from restore_drill_runtime import (
    DrillError,
    RuntimeFixture,
    api_request,
    docker,
    image_digest,
    launch_api,
    launch_provider_guard,
    mapped_postgres_url,
    recovery_states,
    run,
    run_reconciler,
    seed_production_fixture,
    wait_for_api,
    wait_for_postgres,
)


ROOT = Path(__file__).parents[1]
POSTGRES_IMAGE = "postgres:16.6-alpine"
FFMPEG_IMAGE = "jrottenberg/ffmpeg:7.1-alpine"
PASSWORD = "synthetic-local-only"
FINGERPRINT = "sha256:" + "a" * 64


def create_media(media: Path) -> None:
    media.mkdir(parents=True)
    mount = f"{media.resolve()}:/media"
    docker("run", "--rm", "-v", mount, FFMPEG_IMAGE, "-f", "lavfi", "-i", "color=c=blue:s=320x240", "-frames:v", "1", "/media/image.png")
    docker("run", "--rm", "-v", mount, FFMPEG_IMAGE, "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "/media/audio.wav")
    docker("run", "--rm", "-v", mount, FFMPEG_IMAGE, "-loop", "1", "-i", "/media/image.png", "-i", "/media/audio.wav", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "/media/final.mp4")


def verify_http(runtime: RuntimeFixture, media: Path) -> None:
    owner = {"X-API-Key": runtime.owner_key}
    foreign = {"X-API-Key": runtime.foreign_key}
    revoked = {"X-API-Key": runtime.revoked_key}
    project_path = f"/api/creator/projects/{runtime.project_id}"
    if api_request(runtime.port, project_path, owner)[0] != 200:
        raise DrillError("owner project request failed")
    if api_request(runtime.port, project_path, foreign)[0] != 404:
        raise DrillError("cross-workspace project request was not hidden")
    if api_request(runtime.port, project_path, revoked)[0] != 401:
        raise DrillError("revoked key was accepted")
    if api_request(runtime.port, project_path, {})[0] != 401:
        raise DrillError("missing key was accepted")
    media_status, media_body = api_request(
        runtime.port,
        f"/api/creator/workspaces/{runtime.workspace_id}/assets/{runtime.media_id}/content",
        owner,
    )
    video_status, video_body = api_request(
        runtime.port,
        f"/api/creator/runs/{runtime.run_id}/artifacts/{runtime.artifact_id}/download",
        owner,
    )
    if media_status != 200 or video_status != 200:
        raise DrillError("real API protected download failed")
    if hashlib.sha256(media_body).digest() != hashlib.sha256((media / "image.png").read_bytes()).digest():
        raise DrillError("downloaded media checksum mismatch")
    if hashlib.sha256(video_body).digest() != hashlib.sha256((media / "final.mp4").read_bytes()).digest():
        raise DrillError("downloaded final MP4 checksum mismatch")
    downloaded = media / "downloaded-final.mp4"
    downloaded.write_bytes(video_body)
    docker("run", "--rm", "-v", f"{media.resolve()}:/media:ro", FFMPEG_IMAGE, "-v", "error", "-i", "/media/downloaded-final.mp4", "-f", "null", "-")
    print("real API auth: owner=200 workspace-b=404 revoked=401 missing=401")
    print("real API downloads: media=200 final-mp4=200 checksum=verified ffprobe=verified")


def main() -> int:
    if shutil.which("docker") is None:
        print("SKIP: docker is required", file=sys.stderr)
        return 77
    suffix = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:10]
    source, target = f"restore-source-{suffix}", f"restore-target-{suffix}"
    durations: dict[str, float] = {}
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="restore-drill-") as temporary:
        root = Path(temporary)
        bundle, restored = root / "bundle", root / "restored"
        media = bundle / "media"
        api_process: subprocess.Popen[bytes] | None = None
        guard_process: subprocess.Popen[bytes] | None = None
        try:
            create_media(media)
            for container in (source, target):
                docker("run", "-d", "--name", container, "-p", "127.0.0.1::5432", "-e", "POSTGRES_USER=restore", "-e", f"POSTGRES_PASSWORD={PASSWORD}", "-e", "POSTGRES_DB=restore", POSTGRES_IMAGE)
                wait_for_postgres(container)
            source_url = mapped_postgres_url(source, PASSWORD)
            target_url = mapped_postgres_url(target, PASSWORD)
            phase = time.monotonic()
            run(sys.executable, "-m", "alembic", "upgrade", "head", cwd=ROOT / "apps/api", env={**os.environ, "DATABASE_URL": source_url})
            alembic_head = run(
                sys.executable,
                "-m",
                "alembic",
                "current",
                cwd=ROOT / "apps/api",
                env={**os.environ, "DATABASE_URL": source_url},
            ).stdout.split()[0]
            fixture = seed_production_fixture(source, media)
            docker("exec", source, "pg_dump", "-U", "restore", "-d", "restore", "--format=custom", "--file=/tmp/database.dump")
            docker("cp", f"{source}:/tmp/database.dump", str(bundle / "database.dump"))
            durations["backup_seconds"] = time.monotonic() - phase
            manifest = {
                "format_version": 1, "created_at": "synthetic", "release_sha": os.environ.get("GITHUB_SHA", run("git", "rev-parse", "HEAD", cwd=ROOT).stdout.strip()),
                "image_digests": [image_digest(POSTGRES_IMAGE), image_digest(FFMPEG_IMAGE)],
                "alembic_revision": alembic_head, "secret_fingerprint": FINGERPRINT,
                "database_dump": "database.dump", "media_root": "media",
                "files": {path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in (bundle / "database.dump", *sorted(media.iterdir()))},
            }
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            verifier = Path(__file__).with_name("restore_verify.py")
            run(sys.executable, str(verifier), "verify", str(bundle), "--expected-alembic-revision", alembic_head, "--expected-secret-fingerprint", FINGERPRINT)
            phase = time.monotonic()
            docker("cp", str(bundle / "database.dump"), f"{target}:/tmp/database.dump")
            docker("exec", target, "pg_restore", "-U", "restore", "-d", "restore", "--clean", "--if-exists", "/tmp/database.dump")
            run(sys.executable, "-m", "alembic", "upgrade", "head", cwd=ROOT / "apps/api", env={**os.environ, "DATABASE_URL": target_url})
            run(sys.executable, str(verifier), "restore-media", str(bundle), "--target", str(restored), "--expected-alembic-revision", alembic_head, "--expected-secret-fingerprint", FINGERPRINT)
            durations["restore_seconds"] = time.monotonic() - phase
            guard_process, guard_port = launch_provider_guard(root)
            api_process, fixture = launch_api(target_url, restored, fixture, root, guard_port)
            wait_for_api(fixture.port, api_process, root / "api.log")
            verify_http(fixture, restored)
            reconciliation = run_reconciler(target_url)
            states = recovery_states(target)
            if reconciliation.get("rolled_back") != 1 or reconciliation.get("stuck_failed") != 1 or reconciliation.get("errors"):
                raise DrillError(f"unexpected reconciler result: {reconciliation}")
            state_map = dict(line.split("=", 1) for line in states.splitlines())
            if state_map != {"restore-pending": "failed", "restore-queued": "queued", "restore-running": "failed"}:
                raise DrillError(f"unexpected recovered task states: {states}")
            if (root / "provider-invoked").exists():
                raise DrillError("provider-call guard detected an invocation")
            print("production schema: migrated")
            print("provider guard: armed and untouched")
            print("broker recovery: pending=failed queued=queued running=failed")
            print("provider calls: 0")
            evidence = {"github_sha": manifest["release_sha"], "image_digests": manifest["image_digests"], "phase_durations_seconds": {**durations, "total": time.monotonic() - started}, "reconciliation": reconciliation, "recovered_task_states": states.splitlines(), "credential_free": True}
            print("RESTORE_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
            print("RESTORE DRILL PASSED")
            return 0
        finally:
            if api_process is not None:
                api_process.terminate()
                api_process.wait(timeout=15)
            if guard_process is not None:
                guard_process.terminate()
                guard_process.wait(timeout=15)
            subprocess.run(["docker", "rm", "-f", source, target], capture_output=True, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
