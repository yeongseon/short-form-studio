from __future__ import annotations

from pathlib import Path

import pytest

from creator_domain.sanitize import UnsafePathComponent, validate_artifact_path


def test_validate_artifact_path_accepts_path_within_artifact_root(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    target = artifact_root / "101" / "image.png"
    resolved = validate_artifact_path(str(target), str(artifact_root))
    assert resolved == str(target.resolve())


def test_validate_artifact_path_rejects_parent_traversal(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    with pytest.raises(UnsafePathComponent):
        validate_artifact_path(str(artifact_root / ".." / "etc" / "passwd"), str(artifact_root))


def test_validate_artifact_path_rejects_absolute_path_outside_root(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    outside = tmp_path / "outside" / "file.txt"
    with pytest.raises(UnsafePathComponent):
        validate_artifact_path(str(outside), str(artifact_root))


def test_validate_artifact_path_rejects_symlink_escape(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)
    link_path = artifact_root / "link"
    link_path.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(UnsafePathComponent):
        validate_artifact_path(str(link_path / "escape.txt"), str(artifact_root))


def test_validate_artifact_path_rejects_empty_path(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifacts"
    with pytest.raises(UnsafePathComponent):
        validate_artifact_path("", str(artifact_root))
