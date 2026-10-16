from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import assert_never

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_verify.py"


@pytest.fixture(autouse=True)
def _accept_synthetic_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_RESTORE", "/usr/bin/true")


def test_create_and_verify_bundle_when_contents_are_complete(tmp_path: Path) -> None:
    # Given
    bundle = _bundle(tmp_path)

    # When
    created = _run("create", bundle)
    verified = _run(
        "verify",
        bundle,
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    )

    # Then
    assert created.returncode == 0, created.stderr
    assert verified.returncode == 0, verified.stderr
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["alembic_revision"] == "revision-1"
    assert set(manifest["files"]) == {
        "database.dump",
        "media/workspace-a/image.png",
        "media/workspace-a/audio.wav",
        "media/workspace-a/final.mp4",
    }
    assert "secret-v1" not in json.dumps(manifest).lower()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("empty_database", "database dump is empty"),
        ("truncated_database", "checksum mismatch"),
        ("missing_media", "listed file is missing"),
        ("checksum", "checksum mismatch"),
    ],
)
def test_verify_fails_without_touching_original_when_bundle_is_corrupt(
    tmp_path: Path, mutation: str, message: str
) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    target = tmp_path / "original"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("untouched")
    match mutation:
        case "empty_database":
            (bundle / "database.dump").write_bytes(b"")
        case "truncated_database":
            (bundle / "database.dump").write_bytes(b"PGDMP truncated")
        case "missing_media":
            (bundle / "media/workspace-a/audio.wav").unlink()
        case "checksum":
            (bundle / "media/workspace-a/image.png").write_bytes(b"changed")
        case unreachable:
            assert_never(unreachable)

    # When
    result = _run(
        "restore-media",
        bundle,
        "--target",
        str(target),
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    )

    # Then
    assert result.returncode != 0
    assert message in result.stderr.lower()
    assert marker.read_text() == "untouched"


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("--expected-alembic-revision", "revision-2", "alembic revision mismatch"),
        ("--expected-secret-fingerprint", "sha256:fingerprint-v2", "secret fingerprint mismatch"),
    ],
)
def test_verify_fails_when_restore_environment_is_incompatible(
    tmp_path: Path, flag: str, value: str, message: str
) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    args = [
        "verify",
        str(bundle),
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    ]
    args[args.index(flag) + 1] = value

    # When
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False
    )

    # Then
    assert result.returncode != 0
    assert message in result.stderr.lower()


def test_restore_refuses_non_empty_target(tmp_path: Path) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    target = tmp_path / "restore"
    target.mkdir()
    marker = target / "original.txt"
    marker.write_text("preserve")

    # When
    result = _run(
        "restore-media",
        bundle,
        "--target",
        str(target),
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    )

    # Then
    assert result.returncode != 0
    assert "target must be absent" in result.stderr.lower()
    assert marker.read_text() == "preserve"


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [("media_root", "../outside"), ("database_dump", "/tmp/database.dump")],
)
def test_verify_rejects_unsafe_manifest_roots(
    tmp_path: Path, field: str, unsafe_value: str
) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest[field] = unsafe_value
    manifest_path.write_text(json.dumps(manifest))

    # When
    result = _run(
        "verify",
        bundle,
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    )

    # Then
    assert result.returncode != 0
    assert f"unsafe manifest path: {unsafe_value}" in result.stderr


def test_restore_rejects_unlisted_media_without_touching_target(tmp_path: Path) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    (bundle / "media/workspace-a/unlisted.txt").write_text("not checksummed")
    target = tmp_path / "restore"

    # When
    result = _run(
        "restore-media",
        bundle,
        "--target",
        str(target),
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    )

    # Then
    assert result.returncode != 0
    assert "media tree contains unlisted file" in result.stderr
    assert not target.exists()


def test_verify_rejects_unsupported_manifest_version(tmp_path: Path) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["format_version"] = 2
    manifest_path.write_text(json.dumps(manifest))

    # When
    result = _run(
        "verify",
        bundle,
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    )

    # Then
    assert result.returncode != 0
    assert "unsupported manifest format version: 2" in result.stderr


def test_verify_requires_exact_database_dump_checksum(tmp_path: Path) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    del manifest["files"][manifest["database_dump"]]
    manifest_path.write_text(json.dumps(manifest))

    # When
    result = _run(
        "verify",
        bundle,
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    )

    # Then
    assert result.returncode != 0
    assert "database dump must have exactly one checksum" in result.stderr


def test_verify_rejects_symlinked_media(tmp_path: Path) -> None:
    # Given
    bundle = _bundle(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    (bundle / "media/workspace-a/link.txt").symlink_to(outside)

    # When
    result = _run("create", bundle)

    # Then
    assert result.returncode != 0
    assert "media tree contains symlink" in result.stderr


def test_restore_refuses_symlink_target(tmp_path: Path) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    original = tmp_path / "original"
    original.mkdir()
    target = tmp_path / "restore"
    target.symlink_to(original, target_is_directory=True)

    # When
    result = _run(
        "restore-media",
        bundle,
        "--target",
        str(target),
        "--expected-alembic-revision",
        "revision-1",
        "--expected-secret-fingerprint",
        "sha256:fingerprint-v1",
    )

    # Then
    assert result.returncode != 0
    assert "target ancestor must not be a symlink" in result.stderr
    assert list(original.iterdir()) == []


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    media = bundle / "media/workspace-a"
    media.mkdir(parents=True)
    (bundle / "database.dump").write_bytes(b"PGDMP synthetic database")
    (media / "image.png").write_bytes(b"synthetic image")
    (media / "audio.wav").write_bytes(b"synthetic audio")
    (media / "final.mp4").write_bytes(b"synthetic video")
    return bundle


def _run(command: str, bundle: Path, *args: str) -> subprocess.CompletedProcess[str]:
    base = [
        sys.executable,
        str(SCRIPT),
        command,
        str(bundle),
    ]
    if command == "create":
        base.extend(
            [
                "--release-sha",
                "abc123",
                "--image-digest",
                "api=sha256:placeholder",
                "--alembic-revision",
                "revision-1",
                "--secret-fingerprint",
                "sha256:fingerprint-v1",
                "--timestamp",
                "2026-10-16T00:00:00Z",
            ]
        )
    return subprocess.run([*base, *args], capture_output=True, text=True, check=False)
