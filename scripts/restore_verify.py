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
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from restore_manifest import (
    Manifest,
    RestoreError,
    SECRET_FINGERPRINT_PATTERN,
    parse_manifest_json,
)
from restore_paths import checksum, require_contained_path, require_safe_tree
from restore_target import SourceTreeChangedError, copy_tree_to_new_target


def parse_manifest(bundle: Path) -> Manifest:
    manifest_path = bundle / "manifest.json"
    try:
        safe_manifest = require_contained_path(bundle, manifest_path, "manifest")
    except RestoreError as error:
        if "inaccessible" not in str(error):
            raise
        raise RestoreError("manifest is missing")
    return parse_manifest_json(safe_manifest.read_text())


def _safe_relative_path(relative: str) -> PurePosixPath:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RestoreError(f"unsafe manifest path: {relative}")
    return path


def verify_bundle(
    bundle: Path, expected_alembic_revision: str, expected_secret_fingerprint: str
) -> Manifest:
    manifest = parse_manifest(bundle)
    if (
        SECRET_FINGERPRINT_PATTERN.fullmatch(manifest.secret_fingerprint) is None
        or SECRET_FINGERPRINT_PATTERN.fullmatch(expected_secret_fingerprint) is None
    ):
        raise RestoreError(
            "secret fingerprint must be sha256 plus 64 lowercase hex characters"
        )
    if manifest.alembic_revision != expected_alembic_revision:
        raise RestoreError("alembic revision mismatch")
    if manifest.secret_fingerprint != expected_secret_fingerprint:
        raise RestoreError("secret fingerprint mismatch")
    database_dump = bundle / manifest.database_dump
    try:
        safe_database_dump = require_contained_path(bundle, database_dump, "database dump")
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
            safe_path = require_contained_path(bundle, path, "listed file")
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
    safe_media_entries = require_safe_tree(
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
    try:
        bundle_descriptor = os.open(
            bundle, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        )
    except OSError as error:
        raise RestoreError(f"bundle is inaccessible or unsafe: {error}") from error
    if SECRET_FINGERPRINT_PATTERN.fullmatch(args.secret_fingerprint) is None:
        os.close(bundle_descriptor)
        raise RestoreError(
            "secret fingerprint must be sha256 plus 64 lowercase hex characters"
        )
    try:
        database_dump = require_contained_path(
            bundle, bundle / "database.dump", "database dump"
        )
        if not database_dump.is_file() or database_dump.stat().st_size == 0:
            raise RestoreError("database dump is missing or empty")
        media = require_contained_path(bundle, bundle / "media", "media tree")
        if not media.is_dir():
            raise RestoreError("media tree is missing")
        media_entries = require_safe_tree(bundle, media, "media tree")
        files = [database_dump, *(path for path in media_entries if path.is_file())]
        manifest = Manifest(
            created_at=args.timestamp,
            release_sha=args.release_sha,
            image_digests=tuple(args.image_digest),
            alembic_revision=args.alembic_revision,
            secret_fingerprint=args.secret_fingerprint,
            files={
                path.relative_to(bundle).as_posix(): checksum(path)
                for path in sorted(files)
            },
        )
        payload = asdict(manifest)
        payload["image_digests"] = list(manifest.image_digests)
        try:
            manifest_status = os.stat(
                "manifest.json", dir_fd=bundle_descriptor, follow_symlinks=False
            )
        except FileNotFoundError:
            manifest_status = None
        if manifest_status is not None and stat.S_ISLNK(manifest_status.st_mode):
            raise RestoreError("manifest must not be a symlink")
        temporary_name = f".manifest.{os.getpid()}.tmp"
        try:
            descriptor = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=bundle_descriptor,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary_name,
                "manifest.json",
                src_dir_fd=bundle_descriptor,
                dst_dir_fd=bundle_descriptor,
            )
            os.fsync(bundle_descriptor)
        finally:
            try:
                os.unlink(temporary_name, dir_fd=bundle_descriptor)
            except FileNotFoundError:
                pass
    finally:
        os.close(bundle_descriptor)


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
    if target.is_symlink():
        raise RestoreError("target ancestor must not be a symlink")
    if target.exists() or target.is_symlink():
        raise RestoreError("target must be absent")
    try:
        media_root = PurePosixPath(manifest.media_root)
        expected_checksums = {
            PurePosixPath(relative).relative_to(media_root).as_posix(): str(value)
            for relative, value in manifest.files.items()
            if PurePosixPath(relative).is_relative_to(media_root)
        }
        copy_tree_to_new_target(
            bundle / manifest.media_root, target, expected_checksums
        )
    except SourceTreeChangedError as error:
        raise RestoreError(str(error)) from error
    except (FileExistsError, FileNotFoundError, NotADirectoryError, OSError) as error:
        raise RestoreError(f"target ancestor must not be a symlink or target exists: {error}") from error


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
