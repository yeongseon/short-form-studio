from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_verify.py"


@pytest.mark.parametrize(
    "fingerprint",
    [
        "RAW-PROVIDER-SECRET",
        "sha256:abc123",
        f"sha256:{'g' * 64}",
        f"SHA256:{'a' * 64}",
    ],
)
def test_create_rejects_malformed_fingerprint_without_leaking_input(
    tmp_path: Path, fingerprint: str
) -> None:
    # Given
    bundle = tmp_path / "bundle"
    (bundle / "media").mkdir(parents=True)
    (bundle / "database.dump").write_bytes(b"dump")

    # When
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "create",
            str(bundle),
            "--release-sha",
            "abc123",
            "--image-digest",
            "api=sha256:placeholder",
            "--alembic-revision",
            "revision-1",
            "--secret-fingerprint",
            fingerprint,
            "--timestamp",
            "2026-10-16T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    assert result.returncode != 0
    assert "secret fingerprint must be sha256 plus 64 lowercase hex characters" in result.stderr
    assert fingerprint not in result.stdout
    assert fingerprint not in result.stderr
    assert not (bundle / "manifest.json").exists()


@pytest.mark.parametrize("field", ["manifest", "expected"])
def test_verify_rejects_raw_secret_fingerprint(tmp_path: Path, field: str) -> None:
    # Given
    valid = f"sha256:{'a' * 64}"
    bundle = tmp_path / "bundle"
    media = bundle / "media"
    media.mkdir(parents=True)
    dump = bundle / "database.dump"
    dump.write_bytes(b"dump")
    manifest = {
        "format_version": 1,
        "created_at": "2026-10-16T00:00:00Z",
            "release_sha": "abc123def456",
            "image_digests": ["registry/api@sha256:" + "d" * 64],
        "alembic_revision": "revision-1",
        "secret_fingerprint": "RAW-PROVIDER-SECRET" if field == "manifest" else valid,
        "database_dump": "database.dump",
        "media_root": "media",
            "files": {"database.dump": "d" * 64},
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    expected = "RAW-PROVIDER-SECRET" if field == "expected" else valid

    # When
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify",
            str(bundle),
            "--expected-alembic-revision",
            "revision-1",
            "--expected-secret-fingerprint",
            expected,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then
    assert result.returncode != 0
    assert "secret fingerprint must be sha256 plus 64 lowercase hex characters" in result.stderr
    assert "RAW-PROVIDER-SECRET" not in result.stderr
