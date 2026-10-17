from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_verify.py"


@pytest.fixture(autouse=True)
def _accept_synthetic_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_RESTORE", "/usr/bin/true")


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


def test_restore_rejects_intermediate_symlinked_target_ancestor(
    tmp_path: Path,
) -> None:
    # Given
    bundle = _bundle(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    safe = tmp_path / "safe"
    safe.mkdir()
    (safe / "linked").symlink_to(outside, target_is_directory=True)
    target = safe / "linked/inner/restore"

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


def test_restore_parent_swap_does_not_redirect_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    import importlib.util

    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    specification = importlib.util.spec_from_file_location("restore_verify", SCRIPT)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    bundle = _bundle(tmp_path)
    parent = tmp_path / "parent"
    parent.mkdir()
    target = parent / "restore"
    moved_parent = tmp_path / "moved-parent"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_mkdir = module.copy_tree_to_new_target.__globals__["os"].mkdir

    def swap_parent(path: str, mode: int = 0o777, *, dir_fd: int | None = None) -> None:
        if path == target.name and dir_fd is not None:
            parent.rename(moved_parent)
            parent.symlink_to(outside, target_is_directory=True)
        original_mkdir(path, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(module.copy_tree_to_new_target.__globals__["os"], "mkdir", swap_parent)
    arguments = module.parser().parse_args(
        [
            "restore-media",
            str(bundle),
            "--target",
            str(target),
            "--expected-alembic-revision",
            "revision-1",
            "--expected-secret-fingerprint",
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ]
    )

    # When
    module.restore_media(arguments)

    # Then
    assert list(outside.iterdir()) == []
    assert (moved_parent / "restore/workspace-a/image.png").read_bytes() == b"synthetic image"


def test_restore_intermediate_ancestor_swap_does_not_redirect_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    import importlib.util

    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    specification = importlib.util.spec_from_file_location("restore_verify", SCRIPT)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    bundle = _bundle(tmp_path)
    ancestor = tmp_path / "ancestor"
    parent = ancestor / "parent"
    parent.mkdir(parents=True)
    target = parent / "restore"
    moved_ancestor = tmp_path / "moved-ancestor"
    outside = tmp_path / "outside"
    (outside / "parent").mkdir(parents=True)
    original_open = module.copy_tree_to_new_target.__globals__["os"].open
    swapped = False

    def swap_ancestor(
        path: str | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path).name == "ancestor" and not swapped:
            swapped = True
            ancestor.rename(moved_ancestor)
            ancestor.symlink_to(outside, target_is_directory=True)
        return descriptor

    monkeypatch.setattr(
        module.copy_tree_to_new_target.__globals__["os"], "open", swap_ancestor
    )
    arguments = module.parser().parse_args(
        [
            "restore-media",
            str(bundle),
            "--target",
            str(target),
            "--expected-alembic-revision",
            "revision-1",
            "--expected-secret-fingerprint",
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ]
    )

    # When
    module.restore_media(arguments)

    # Then
    assert list((outside / "parent").iterdir()) == []
    restored = moved_ancestor / "parent/restore/workspace-a/image.png"
    assert restored.read_bytes() == b"synthetic image"


def test_restore_rejects_source_file_swapped_after_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    import importlib.util

    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    specification = importlib.util.spec_from_file_location("restore_verify", SCRIPT)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    bundle = _bundle(tmp_path)
    source = bundle / "media/workspace-a/image.png"
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"external secret")
    target = tmp_path / "restore"
    original_copy = module.copy_tree_to_new_target

    def swap_source(
        source_root: Path, target_root: Path, expected_checksums: dict[str, str]
    ) -> None:
        source.unlink()
        source.symlink_to(outside)
        original_copy(source_root, target_root, expected_checksums)

    monkeypatch.setattr(module, "copy_tree_to_new_target", swap_source)
    arguments = module.parser().parse_args(
        [
            "restore-media",
            str(bundle),
            "--target",
            str(target),
            "--expected-alembic-revision",
            "revision-1",
            "--expected-secret-fingerprint",
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ]
    )

    # When / Then
    with pytest.raises(module.RestoreError, match="source changed during restore"):
        module.restore_media(arguments)
    assert not (target / "workspace-a/image.png").exists()


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
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
            "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
