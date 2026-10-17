from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import NewType, TypedDict


Checksum = NewType("Checksum", str)
SECRET_FINGERPRINT_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
CHECKSUM_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_DIGEST_PATTERN = re.compile(r"[^@]+@sha256:[0-9a-f]{64}\Z")
RELEASE_SHA_PATTERN = re.compile(r"[0-9a-f]{6,64}\Z")


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


def parse_manifest_json(payload: str) -> Manifest:
    try:
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            raise RestoreError("manifest is invalid: root must be an object")
        required = set(ManifestJson.__required_keys__)
        if set(decoded) != required:
            raise RestoreError("manifest is invalid: fields do not match schema")
        raw = decoded
        string_fields = (
            "created_at", "release_sha", "alembic_revision",
            "secret_fingerprint", "database_dump", "media_root",
        )
        if any(not isinstance(raw[field], str) for field in string_fields):
            raise RestoreError("manifest is invalid: string field has wrong type")
        if not isinstance(raw["format_version"], int):
            raise RestoreError("manifest is invalid: format_version must be an integer")
        if not isinstance(raw["image_digests"], list) or not raw["image_digests"]:
            raise RestoreError("manifest is invalid: image_digests must be a non-empty list")
        if any(not isinstance(value, str) or IMAGE_DIGEST_PATTERN.fullmatch(value) is None for value in raw["image_digests"]):
            raise RestoreError("manifest is invalid: image digest format")
        if RELEASE_SHA_PATTERN.fullmatch(raw["release_sha"]) is None:
            raise RestoreError("manifest is invalid: release_sha format")
        if not isinstance(raw["files"], dict) or not raw["files"]:
            raise RestoreError("manifest is invalid: files must be a non-empty object")
        if any(not isinstance(path, str) or not isinstance(value, str) or CHECKSUM_PATTERN.fullmatch(value) is None for path, value in raw["files"].items()):
            raise RestoreError("manifest is invalid: file checksum format")
        if raw["format_version"] != 1:
            raise RestoreError(f"unsupported manifest format version: {raw['format_version']}")
        for relative in (raw["database_dump"], raw["media_root"], *raw["files"]):
            path = PurePosixPath(relative)
            if path.is_absolute() or ".." in path.parts:
                raise RestoreError(f"unsafe manifest path: {relative}")
        return Manifest(
            created_at=raw["created_at"], release_sha=raw["release_sha"],
            image_digests=tuple(raw["image_digests"]),
            alembic_revision=raw["alembic_revision"],
            secret_fingerprint=raw["secret_fingerprint"],
            files={path: Checksum(value) for path, value in raw["files"].items()},
            format_version=raw["format_version"], database_dump=raw["database_dump"],
            media_root=raw["media_root"],
        )
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise RestoreError(f"manifest is invalid: {error}") from error
