from __future__ import annotations

import os
import shutil
from pathlib import Path


def copy_tree_to_new_target(source: Path, target: Path) -> None:
    """Create and populate target relative to a pinned, nofollow parent descriptor."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    parent_descriptor = os.open(target.parent, flags)
    try:
        os.mkdir(target.name, mode=0o700, dir_fd=parent_descriptor)
        target_descriptor = os.open(target.name, flags, dir_fd=parent_descriptor)
        try:
            _copy_directory(source, target_descriptor)
        finally:
            os.close(target_descriptor)
    finally:
        os.close(parent_descriptor)


def _copy_directory(source: Path, destination_descriptor: int) -> None:
    for entry in source.iterdir():
        if entry.is_dir():
            os.mkdir(entry.name, mode=0o700, dir_fd=destination_descriptor)
            child_descriptor = os.open(
                entry.name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=destination_descriptor,
            )
            try:
                _copy_directory(entry, child_descriptor)
            finally:
                os.close(child_descriptor)
            continue
        descriptor = os.open(
            entry.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=destination_descriptor,
        )
        with entry.open("rb") as source_handle, os.fdopen(descriptor, "wb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
