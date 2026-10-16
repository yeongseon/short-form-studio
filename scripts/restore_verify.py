#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run scripts/restore_verify.py --help
# 3. Or make executable and run:
#      chmod +x scripts/restore_verify.py && ./scripts/restore_verify.py --help
# ──────────────────

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import NewType, TypedDict


Checksum = NewType("Checksum", str)


class ManifestJson(TypedDict):
    format_version: int
    created_at: str
    release_sha: str
    image_digests: list[str]
    alembic_revision: str
    secret_fingerprint: str
    database_dump: str
    media_root: str
    files: dict[str, str]


@dataclass(frozen=True, slots=True)
class Manifest:
    created_at: str
    release_sha: str
    image_digests: tuple[str, ...]
    alembic_revision: str
    secret_fingerprint: str
    files: dict[str, Checksum]
    format_version: int = 1
    database_dump: str = "database.dump"
    media_root: str = "media"


@dataclass(frozen=True, slots=True)
class RestoreError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


def checksum(path: Path) -> Checksum:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return Checksum(digest.hexdigest())


def _require_contained_path(bundle: Path, path: Path, label: str) -> Path:
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


def _require_safe_tree(bundle: Path, root: Path, label: str) -> list[Path]:
    safe_root = _require_contained_path(bundle, root, label)
    entries: list[Path] = []
    for directory, directory_names, file_names in os.walk(safe_root, followlinks=False):
        directory_path = Path(directory)
        for name in [*directory_names, *file_names]:
            entry = directory_path / name
            _require_contained_path(bundle, entry, label)
            entries.append(entry)
    return entries


def parse_manifest(bundle: Path) -> Manifest:
    manifest_path = bundle / "manifest.json"
    try:
        safe_manifest = _require_contained_path(bundle, manifest_path, "manifest")
    except RestoreError as error:
        if "inaccessible" not in str(error):
            raise
        raise RestoreError("manifest is missing")
    try:
        raw: ManifestJson = json.loads(safe_manifest.read_text())
        if raw["format_version"] != 1:
            raise RestoreError(
                f"unsupported manifest format version: {raw['format_version']}"
            )
        for relative in (raw["database_dump"], raw["media_root"]):
            _safe_relative_path(relative)
        files = raw["files"]
        for relative in files:
            _safe_relative_path(relative)
        return Manifest(
            created_at=raw["created_at"],
            release_sha=raw["release_sha"],
            image_digests=tuple(raw["image_digests"]),
            alembic_revision=raw["alembic_revision"],
            secret_fingerprint=raw["secret_fingerprint"],
            files={path: Checksum(value) for path, value in files.items()},
            format_version=raw["format_version"],
            database_dump=raw["database_dump"],
            media_root=raw["media_root"],
        )
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise RestoreError(f"manifest is invalid: {error}") from error


def _safe_relative_path(relative: str) -> PurePosixPath:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RestoreError(f"unsafe manifest path: {relative}")
    return path


def verify_bundle(
    bundle: Path, expected_alembic_revision: str, expected_secret_fingerprint: str
) -> Manifest:
    manifest = parse_manifest(bundle)
    if manifest.alembic_revision != expected_alembic_revision:
        raise RestoreError("alembic revision mismatch")
    if manifest.secret_fingerprint != expected_secret_fingerprint:
        raise RestoreError("secret fingerprint mismatch")
    database_dump = bundle / manifest.database_dump
    try:
        safe_database_dump = _require_contained_path(bundle, database_dump, "database dump")
    except RestoreError as error:
        if "inaccessible" not in str(error):
            raise
        raise RestoreError("database dump is missing")
    if not safe_database_dump.is_file():
        raise RestoreError("database dump is missing")
    if safe_database_dump.stat().st_size == 0:
        raise RestoreError("database dump is empty")
    database_entries = [
        relative for relative in manifest.files if relative == manifest.database_dump
    ]
    if len(database_entries) != 1:
        raise RestoreError("database dump must have exactly one checksum")
    pg_restore = os.environ.get("PG_RESTORE") or shutil.which("pg_restore")
    if pg_restore is None:
        raise RestoreError("pg_restore is required to validate database dump")
    archive = subprocess.run(
        [pg_restore, "--list", str(safe_database_dump)],
        capture_output=True,
        text=True,
        check=False,
    )
    if archive.returncode != 0:
        raise RestoreError("database dump is not a valid custom-format archive")
    for relative, expected_checksum in manifest.files.items():
        path = bundle / relative
        try:
            safe_path = _require_contained_path(bundle, path, "listed file")
        except RestoreError as error:
            if "inaccessible" not in str(error):
                raise
            raise RestoreError(f"listed file is missing: {relative}")
        if not safe_path.is_file():
            raise RestoreError(f"listed file is missing: {relative}")
        if checksum(safe_path) != expected_checksum:
            raise RestoreError(f"checksum mismatch: {relative}")
    media_root = PurePosixPath(manifest.media_root)
    listed_media = {
        PurePosixPath(relative)
        for relative in manifest.files
        if PurePosixPath(relative).is_relative_to(media_root)
    }
    safe_media_entries = _require_safe_tree(
        bundle, bundle / manifest.media_root, "media tree"
    )
    actual_media = {
        path.relative_to(bundle).as_posix()
        for path in safe_media_entries
        if path.is_file()
    }
    if actual_media != {path.as_posix() for path in listed_media}:
        raise RestoreError("media tree contains unlisted file")
    return manifest


def create_manifest(args: argparse.Namespace) -> None:
    bundle = Path(args.bundle)
    database_dump = _require_contained_path(bundle, bundle / "database.dump", "database dump")
    if not database_dump.is_file() or database_dump.stat().st_size == 0:
        raise RestoreError("database dump is missing or empty")
    media = _require_contained_path(bundle, bundle / "media", "media tree")
    if not media.is_dir():
        raise RestoreError("media tree is missing")
    media_entries = _require_safe_tree(bundle, media, "media tree")
    files = [database_dump, *(path for path in media_entries if path.is_file())]
    manifest = Manifest(
        created_at=args.timestamp,
        release_sha=args.release_sha,
        image_digests=tuple(args.image_digest),
        alembic_revision=args.alembic_revision,
        secret_fingerprint=args.secret_fingerprint,
        files={path.relative_to(bundle).as_posix(): checksum(path) for path in sorted(files)},
    )
    payload = asdict(manifest)
    payload["image_digests"] = list(manifest.image_digests)
    (bundle / "manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def verify(args: argparse.Namespace) -> None:
    verify_bundle(
        Path(args.bundle), args.expected_alembic_revision, args.expected_secret_fingerprint
    )


def restore_media(args: argparse.Namespace) -> None:
    bundle = Path(args.bundle)
    manifest = verify_bundle(
        bundle, args.expected_alembic_revision, args.expected_secret_fingerprint
    )
    target = Path(args.target)
    current = target
    existing_ancestors: list[Path] = []
    while not current.exists() and not current.is_symlink():
        current = current.parent
    while True:
        existing_ancestors.append(current)
        if current == current.parent:
            break
        current = current.parent
    if any(path.is_symlink() for path in existing_ancestors):
        raise RestoreError("target ancestor must not be a symlink")
    if target.exists() or target.is_symlink():
        raise RestoreError("target must be absent")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(bundle / manifest.media_root, target)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Create and verify coordinated restore bundles")
    commands = root.add_subparsers(required=True)
    create = commands.add_parser("create")
    create.add_argument("bundle")
    create.add_argument("--release-sha", required=True)
    create.add_argument("--image-digest", action="append", required=True)
    create.add_argument("--alembic-revision", required=True)
    create.add_argument("--secret-fingerprint", required=True)
    create.add_argument("--timestamp", required=True)
    create.set_defaults(handler=create_manifest)
    for name, handler in (("verify", verify), ("restore-media", restore_media)):
        command = commands.add_parser(name)
        command.add_argument("bundle")
        command.add_argument("--expected-alembic-revision", required=True)
        command.add_argument("--expected-secret-fingerprint", required=True)
        if name == "restore-media":
            command.add_argument("--target", required=True)
        command.set_defaults(handler=handler)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        args.handler(args)
    except RestoreError as error:
        print(f"restore verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
