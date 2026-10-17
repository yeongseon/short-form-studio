from __future__ import annotations

import hashlib
import os
from pathlib import Path

from restore_manifest import Checksum, RestoreError


def checksum(path: Path) -> Checksum:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return Checksum(digest.hexdigest())


def require_contained_path(bundle: Path, path: Path, label: str) -> Path:
    bundle_root = bundle.resolve(strict=True)
    try:
        bundle.lstat()
    except OSError as error:
        raise RestoreError(f"{label} is inaccessible: {error}") from error
    if bundle.is_symlink():
        raise RestoreError("bundle must not be a symlink")
    try:
        relative = path.relative_to(bundle)
    except ValueError as error:
        raise RestoreError(f"{label} escapes bundle") from error
    current = bundle
    for part in relative.parts:
        current /= part
        try:
            current.lstat()
        except OSError as error:
            raise RestoreError(f"{label} is inaccessible: {error}") from error
        if current.is_symlink():
            raise RestoreError(f"{label} contains symlink: {relative}")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(bundle_root):
        raise RestoreError(f"{label} escapes bundle: {relative}")
    return resolved


def require_safe_tree(bundle: Path, root: Path, label: str) -> list[Path]:
    safe_root = require_contained_path(bundle, root, label)
    entries: list[Path] = []
    for directory, directory_names, file_names in os.walk(safe_root, followlinks=False):
        directory_path = Path(directory)
        for name in [*directory_names, *file_names]:
            entry = directory_path / name
            require_contained_path(bundle, entry, label)
            entries.append(entry)
    return entries
