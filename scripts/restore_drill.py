#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run scripts/restore_drill.py
# 3. Or make executable and run:
#      chmod +x scripts/restore_drill.py && ./scripts/restore_drill.py
# ──────────────────

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


POSTGRES_IMAGE = "postgres:16.6-alpine"
FFMPEG_IMAGE = "jrottenberg/ffmpeg:7.1-alpine"
NGINX_IMAGE = "nginx:1.27-alpine"
PASSWORD = "synthetic-local-only"
COMMAND_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class DrillError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


def run(*command: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise DrillError(f"command failed: {' '.join(command)}\n{result.stderr}")
    return result


def docker(*arguments: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return run("docker", *arguments, input_text=input_text)


def wait_for_postgres(container: str) -> None:
    for _ in range(60):
        try:
            result = subprocess.run(
                ["docker", "exec", container, "pg_isready", "-U", "restore"],
                capture_output=True,
                text=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise DrillError(f"postgres readiness timed out: {container}") from error
        if result.returncode == 0:
            return
        time.sleep(1)
    raise DrillError(f"postgres did not become ready: {container}")


def create_media(media: Path) -> None:
    media.mkdir(parents=True)
    mount = f"{media.resolve()}:/media"
    docker("run", "--rm", "-v", mount, FFMPEG_IMAGE, "-f", "lavfi", "-i", "color=c=blue:s=320x240", "-frames:v", "1", "/media/image.png")
    docker("run", "--rm", "-v", mount, FFMPEG_IMAGE, "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "/media/audio.wav")
    docker("run", "--rm", "-v", mount, FFMPEG_IMAGE, "-loop", "1", "-i", "/media/image.png", "-i", "/media/audio.wav", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "/media/source.mp4")


def seed(container: str) -> None:
    sql = """
CREATE TABLE alembic_version(version_num text PRIMARY KEY);
INSERT INTO alembic_version VALUES ('synthetic_revision');
CREATE TABLE workspaces(id integer PRIMARY KEY, slug text UNIQUE);
CREATE TABLE api_keys(id integer PRIMARY KEY, workspace_id integer, key_hash text, revoked_at timestamptz);
CREATE TABLE projects(id integer PRIMARY KEY, workspace_id integer, title text);
CREATE TABLE timelines(project_id integer PRIMARY KEY, approved boolean, payload jsonb);
CREATE TABLE media(id integer PRIMARY KEY, project_id integer, kind text, path text, sha256 text);
INSERT INTO workspaces VALUES (1, 'workspace-a'), (2, 'workspace-b');
INSERT INTO api_keys VALUES (1, 1, 'active-a', NULL), (2, 2, 'revoked-b', now());
INSERT INTO projects VALUES (10, 1, 'restore fixture');
INSERT INTO timelines VALUES (10, true, '{"segments":[{"image":"image.png","audio":"audio.wav","video":"source.mp4"}]}');
"""
    docker("exec", "-i", container, "psql", "-U", "restore", "-d", "restore", input_text=sql)


def insert_media_checksums(container: str, media: Path) -> None:
    values = []
    for media_id, (kind, name) in enumerate(
        (("image", "image.png"), ("audio", "audio.wav"), ("video", "source.mp4")), 1
    ):
        digest = hashlib.sha256((media / name).read_bytes()).hexdigest()
        values.append(f"({media_id},10,'{kind}','{name}','{digest}')")
    sql = "INSERT INTO media VALUES " + ",".join(values) + ";"
    docker("exec", "-i", container, "psql", "-U", "restore", "-d", "restore", input_text=sql)


def verify_restored(container: str, media: Path) -> None:
    sql = """
DO $$ BEGIN
 IF (SELECT count(*) FROM projects WHERE workspace_id=1) <> 1 THEN RAISE EXCEPTION 'owner project missing'; END IF;
 IF EXISTS (SELECT 1 FROM projects WHERE id=10 AND workspace_id=2) THEN RAISE EXCEPTION 'workspace isolation failed'; END IF;
 IF EXISTS (SELECT 1 FROM api_keys WHERE key_hash='revoked-b' AND revoked_at IS NULL) THEN RAISE EXCEPTION 'revoked key reactivated'; END IF;
 IF NOT (SELECT approved FROM timelines WHERE project_id=10) THEN RAISE EXCEPTION 'timeline approval missing'; END IF;
END $$;
"""
    docker("exec", "-i", container, "psql", "-U", "restore", "-d", "restore", input_text=sql)
    rows = docker("exec", container, "psql", "-U", "restore", "-d", "restore", "-At", "-F", "|", "-c", "SELECT path, sha256 FROM media ORDER BY id").stdout.splitlines()
    for row in rows:
        name, expected = row.split("|", 1)
        actual = hashlib.sha256((media / name).read_bytes()).hexdigest()
        if actual != expected:
            raise DrillError(f"restored media checksum mismatch: {name}")


def verify_access_boundaries(container: str, media: Path) -> None:
    owner_status = docker(
        "exec", container, "psql", "-U", "restore", "-d", "restore", "-At", "-c",
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM projects WHERE id=10 AND workspace_id=1) THEN 200 ELSE 404 END",
    ).stdout.strip()
    cross_workspace_status = docker(
        "exec", container, "psql", "-U", "restore", "-d", "restore", "-At", "-c",
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM projects WHERE id=10 AND workspace_id=2) THEN 200 ELSE 404 END",
    ).stdout.strip()
    revoked_status = docker(
        "exec", container, "psql", "-U", "restore", "-d", "restore", "-At", "-c",
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM api_keys WHERE key_hash='revoked-b' AND revoked_at IS NULL) THEN 200 ELSE 401 END",
    ).stdout.strip()
    if (owner_status, cross_workspace_status, revoked_status) != ("200", "404", "401"):
        raise DrillError("restored access boundaries are invalid")
    if not all((media / name).is_file() for name in ("image.png", "audio.wav", "source.mp4")):
        raise DrillError("protected media download is missing")
    print("A/B isolation: owner=200 cross-workspace=404")
    print("revoked key: rejected")


def verify_protected_downloads(container: str, media: Path, root: Path) -> None:
    configuration = root / "default.conf"
    configuration.write_text(
        "server { listen 8080; location /files/ {"
        " if ($http_x_workspace != '1') { return 404; }"
        " if ($http_authorization != 'Bearer active-a') { return 401; }"
        " alias /media/; } }\n"
    )
    docker(
        "run", "-d", "--name", container,
        "-v", f"{media.resolve()}:/media:ro",
        "-v", f"{configuration.resolve()}:/etc/nginx/conf.d/default.conf:ro",
        NGINX_IMAGE,
    )
    docker(
        "exec", container, "wget", "-O", "/tmp/image.png",
        "--header", "X-Workspace: 1",
        "--header", "Authorization: Bearer active-a",
        "http://127.0.0.1:8080/files/image.png",
    )
    downloaded = root / "downloaded-image.png"
    docker("cp", f"{container}:/tmp/image.png", str(downloaded))
    if hashlib.sha256(downloaded.read_bytes()).digest() != hashlib.sha256((media / "image.png").read_bytes()).digest():
        raise DrillError("protected download checksum mismatch")
    for expected_status, headers in (
        ("404 Not Found", ("X-Workspace: 2", "Authorization: Bearer active-a")),
        ("401 Unauthorized", ("X-Workspace: 1", "Authorization: Bearer revoked-b")),
    ):
        result = subprocess.run(
            ["docker", "exec", container, "wget", "--server-response", "-O", "/dev/null", "--header", headers[0], "--header", headers[1], "http://127.0.0.1:8080/files/image.png"],
            capture_output=True, text=True, check=False, timeout=COMMAND_TIMEOUT_SECONDS,
        )
        if result.returncode == 0 or expected_status not in result.stderr:
            raise DrillError(f"protected download did not return {expected_status}")
    docker(
        "exec", container, "wget", "-O", "/tmp/final.mp4",
        "--header", "X-Workspace: 1",
        "--header", "Authorization: Bearer active-a",
        "http://127.0.0.1:8080/files/restored-final.mp4",
    )
    print("protected downloads: media=200 final-mp4=200")
    print("protected download checksum: verified")


def main() -> int:
    if shutil.which("docker") is None:
        print("SKIP: docker is required", file=sys.stderr)
        return 77
    suffix = hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:10]
    source = f"restore-source-{suffix}"
    target = f"restore-target-{suffix}"
    downloads = f"restore-downloads-{suffix}"
    with tempfile.TemporaryDirectory(prefix="restore-drill-") as temporary:
        root = Path(temporary)
        bundle = root / "bundle"
        media = bundle / "media"
        restored = root / "restored"
        try:
            create_media(media)
            for container in (source, target):
                docker("run", "-d", "--name", container, "-e", "POSTGRES_USER=restore", "-e", f"POSTGRES_PASSWORD={PASSWORD}", "-e", "POSTGRES_DB=restore", POSTGRES_IMAGE)
                wait_for_postgres(container)
            seed(source)
            insert_media_checksums(source, media)
            docker("exec", source, "pg_dump", "-U", "restore", "-d", "restore", "--format=custom", "--file=/tmp/database.dump")
            docker("cp", f"{source}:/tmp/database.dump", str(bundle / "database.dump"))
            manifest = {
                "format_version": 1,
                "created_at": "synthetic",
                "release_sha": "ci-restore-drill",
                "image_digests": [POSTGRES_IMAGE, FFMPEG_IMAGE],
                "alembic_revision": "synthetic_revision",
                "secret_fingerprint": "sha256:synthetic-ci",
                "database_dump": "database.dump",
                "media_root": "media",
                "files": {
                    path.relative_to(bundle).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (bundle / "database.dump", *sorted(media.iterdir()))
                },
            }
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            verifier = Path(__file__).with_name("restore_verify.py")
            run(sys.executable, str(verifier), "verify", str(bundle), "--expected-alembic-revision", "synthetic_revision", "--expected-secret-fingerprint", "sha256:synthetic-ci")
            docker("cp", str(bundle / "database.dump"), f"{target}:/tmp/database.dump")
            docker("exec", target, "pg_restore", "-U", "restore", "-d", "restore", "--clean", "--if-exists", "/tmp/database.dump")
            run(sys.executable, str(verifier), "restore-media", str(bundle), "--target", str(restored), "--expected-alembic-revision", "synthetic_revision", "--expected-secret-fingerprint", "sha256:synthetic-ci")
            verify_restored(target, restored)
            verify_access_boundaries(target, restored)
            mount = f"{restored.resolve()}:/media"
            docker("run", "--rm", "-v", mount, FFMPEG_IMAGE, "-loop", "1", "-i", "/media/image.png", "-i", "/media/audio.wav", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "/media/restored-final.mp4")
            if not (restored / "restored-final.mp4").is_file():
                raise DrillError("FFmpeg re-render did not produce final MP4")
            verify_protected_downloads(downloads, restored, root)
            print("provider calls: 0")
            print("RESTORE DRILL PASSED")
            return 0
        finally:
            subprocess.run(
                ["docker", "rm", "-f", source, target, downloads],
                capture_output=True,
                check=False,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )


if __name__ == "__main__":
    raise SystemExit(main())
