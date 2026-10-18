from __future__ import annotations

import os
import hashlib
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceTreeChangedError(OSError):
    relative_path: str

    def __str__(self) -> str:
        return f"source changed during restore: {self.relative_path}"


def copy_tree_to_new_target(
    source: Path, target: Path, expected_checksums: dict[str, str]
) -> None:
    """Create and populate target relative to a pinned, nofollow parent descriptor."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    source_descriptor = os.open(source, flags)
    parent_descriptor = _open_directory_path(target.parent, flags)
    try:
        os.mkdir(target.name, mode=0o700, dir_fd=parent_descriptor)
        target_descriptor = os.open(target.name, flags, dir_fd=parent_descriptor)
        try:
            copied_paths: set[str] = set()
            _copy_directory(
                source_descriptor,
                target_descriptor,
                expected_checksums,
                Path(),
                copied_paths,
            )
            if copied_paths != set(expected_checksums):
                missing = sorted(set(expected_checksums) - copied_paths)
                raise SourceTreeChangedError(missing[0] if missing else ".")
        except OSError:
            _remove_directory_contents(target_descriptor)
            os.close(target_descriptor)
            os.rmdir(target.name, dir_fd=parent_descriptor)
            target_descriptor = -1
            raise
        finally:
            if target_descriptor >= 0:
                os.close(target_descriptor)
    finally:
        os.close(parent_descriptor)
        os.close(source_descriptor)


def _open_directory_path(path: Path, flags: int) -> int:
    absolute = path.absolute()
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            child_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_descriptor
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


def _copy_directory(
    source_descriptor: int,
    destination_descriptor: int,
    expected_checksums: dict[str, str],
    relative_root: Path,
    copied_paths: set[str],
) -> None:
    for name in os.listdir(source_descriptor):
        relative_path = relative_root / name
        source_status = os.stat(name, dir_fd=source_descriptor, follow_symlinks=False)
        if stat.S_ISDIR(source_status.st_mode):
            os.mkdir(name, mode=0o700, dir_fd=destination_descriptor)
            source_child_descriptor = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=source_descriptor,
            )
            child_descriptor = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=destination_descriptor,
            )
            try:
                _copy_directory(
                    source_child_descriptor,
                    child_descriptor,
                    expected_checksums,
                    relative_path,
                    copied_paths,
                )
            finally:
                os.close(child_descriptor)
                os.close(source_child_descriptor)
            continue
        if not stat.S_ISREG(source_status.st_mode):
            raise SourceTreeChangedError(relative_path.as_posix())
        source_file_descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_descriptor
        )
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=destination_descriptor,
        )
        digest = hashlib.sha256()
        with os.fdopen(source_file_descriptor, "rb") as source_handle, os.fdopen(
            descriptor, "wb"
        ) as target_handle:
            for block in iter(lambda: source_handle.read(1024 * 1024), b""):
                digest.update(block)
                target_handle.write(block)
        expected_checksum = expected_checksums.get(relative_path.as_posix())
        if expected_checksum is None or digest.hexdigest() != expected_checksum:
            raise SourceTreeChangedError(relative_path.as_posix())
        copied_paths.add(relative_path.as_posix())


def _remove_directory_contents(directory_descriptor: int) -> None:
    for name in os.listdir(directory_descriptor):
        status = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if stat.S_ISDIR(status.st_mode):
            child_descriptor = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
            try:
                _remove_directory_contents(child_descriptor)
            finally:
                os.close(child_descriptor)
            os.rmdir(name, dir_fd=directory_descriptor)
        else:
            os.unlink(name, dir_fd=directory_descriptor)
