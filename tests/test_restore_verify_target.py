from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_verify.py"


def test_restore_rejects_symlinked_target_ancestor(tmp_path: Path) -> None:
    # Given
    bundle = _bundle(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    target = linked_parent / "restore"

    # When
    result = _restore(bundle, target)

    # Then
    assert result.returncode != 0
    assert "target ancestor must not be a symlink" in result.stderr
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("existing_content", [False, True])
def test_restore_requires_absent_target(
    tmp_path: Path, existing_content: bool
) -> None:
    # Given
    bundle = _bundle(tmp_path)
    target = tmp_path / "restore"
    target.mkdir()
    if existing_content:
        (target / "existing.txt").write_text("preserve")

    # When
    result = _restore(bundle, target)

    # Then
    assert result.returncode != 0
    assert "target must be absent" in result.stderr


def test_restore_exclusive_create_rejects_concurrent_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    import importlib.util

    specification = importlib.util.spec_from_file_location("restore_verify", SCRIPT)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    bundle = _bundle(tmp_path)
    target = tmp_path / "restore"
    original_copytree = module.shutil.copytree

    def concurrent_copytree(source: Path, destination: Path) -> Path:
        destination.mkdir()
        (destination / "concurrent.txt").write_text("preserve")
        return original_copytree(source, destination)

    monkeypatch.setattr(module.shutil, "copytree", concurrent_copytree)
    arguments = module.parser().parse_args(
        [
            "restore-media",
            str(bundle),
            "--target",
            str(target),
            "--expected-alembic-revision",
            "revision-1",
            "--expected-secret-fingerprint",
            "sha256:fingerprint-v1",
        ]
    )

    # When / Then
    with pytest.raises(FileExistsError):
        module.restore_media(arguments)
    assert (target / "concurrent.txt").read_text() == "preserve"


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    media = bundle / "media/workspace-a"
    media.mkdir(parents=True)
    (bundle / "database.dump").write_bytes(b"PGDMP synthetic database")
    (media / "image.png").write_bytes(b"synthetic image")
    created = subprocess.run(
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
            "sha256:fingerprint-v1",
            "--timestamp",
            "2026-10-16T00:00:00Z",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    return bundle


def _restore(bundle: Path, target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "restore-media",
            str(bundle),
            "--target",
            str(target),
            "--expected-alembic-revision",
            "revision-1",
            "--expected-secret-fingerprint",
            "sha256:fingerprint-v1",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
