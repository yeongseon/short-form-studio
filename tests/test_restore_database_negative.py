from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_verify.py"


def test_checksummed_corrupt_dump_cannot_restore_to_fresh_database(
    tmp_path: Path,
) -> None:
    # Given
    if shutil.which("docker") is None:
        pytest.skip("docker is required for PostgreSQL restore validation")
    bundle = tmp_path / "bundle"
    (bundle / "media").mkdir(parents=True)
    dump = bundle / "database.dump"
    dump.write_bytes(b"PGDMP\x01\x0e truncated")
    digest = hashlib.sha256(dump.read_bytes()).hexdigest()
    manifest = {
        "format_version": 1,
        "created_at": "2026-10-16T00:00:00Z",
        "release_sha": "abc123",
        "image_digests": ["postgres@sha256:placeholder"],
        "alembic_revision": "revision-1",
        "secret_fingerprint": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "database_dump": "database.dump",
        "media_root": "media",
        "files": {"database.dump": digest},
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    container = f"restore-corrupt-{uuid.uuid4().hex[:12]}"

    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                "-e",
                "POSTGRES_PASSWORD=restore",
                "postgres:16.6-alpine",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # When
        validation = subprocess.run(
            [sys.executable, str(SCRIPT), "verify", str(bundle), "--expected-alembic-revision", "revision-1", "--expected-secret-fingerprint", "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
            capture_output=True,
            text=True,
            check=False,
        )
        restore = subprocess.run(
            ["docker", "exec", "-i", container, "pg_restore", "-U", "postgres", "-d", "postgres"],
            input=dump.read_bytes(),
            capture_output=True,
            check=False,
        )

        # Then
        assert validation.returncode != 0
        assert "database dump is not a valid custom-format archive" in validation.stderr
        assert restore.returncode != 0
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container], capture_output=True, check=False
        )
