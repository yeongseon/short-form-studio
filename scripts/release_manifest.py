#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pydantic>=2.10,<3"]
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv or pip install needed):
#      uv run scripts/release_manifest.py validate release.json
# 3. Or make executable and run:
#      chmod +x scripts/release_manifest.py && ./scripts/release_manifest.py validate release.json
# ──────────────────

from __future__ import annotations

import json
import ipaddress
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, NewType, assert_never
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError


Digest = NewType("Digest", str)
ContractVersion = NewType("ContractVersion", str)
Sha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
DigestText = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
Revision = Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z][0-9A-Za-z_-]*$")]
Tag = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.[1-9][0-9]*$")]
PLACEHOLDER_HOSTS: Final = frozenset({"example.com", "localhost", "127.0.0.1"})
SERVICE_REPOSITORIES: Final = {
    "api": "api",
    "worker": "worker",
    "studio": "studio-web",
}


class Command(StrEnum):
    VALIDATE = "validate"
    VERIFY_DB = "verify-db"
    VERIFY_DB_COMPATIBLE = "verify-db-compatible"
    VERIFY_RUNTIME = "verify-runtime"


class ImageIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: Annotated[str, StringConstraints(min_length=1, pattern=r"^ghcr\.io/.+/.+$")]
    digest: DigestText


class ReleaseImages(BaseModel):
    model_config = ConfigDict(frozen=True)

    api: ImageIdentity
    worker: ImageIdentity
    studio: ImageIdentity


class ReleaseManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    release_tag: Tag
    source_sha: Sha
    images: ReleaseImages
    db_revision: Revision
    schema_contract: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*$")]
    queue_contract: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]*$")]


class RuntimeIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    api_source_sha: Sha
    worker_source_shas: list[Sha]
    studio_source_sha: Sha
    api_digest: DigestText
    worker_digest: DigestText
    studio_digest: DigestText


@dataclass(frozen=True, slots=True)
class ManifestError(ValueError):
    detail: str

    def __str__(self) -> str:
        return self.detail


def load_manifest(path: Path) -> ReleaseManifest:
    return ReleaseManifest.model_validate_json(path.read_text())


def assert_deploy_target(target: str) -> None:
    normalized = target.strip()
    parsed = urlparse(normalized)
    hostname = (parsed.hostname or "").lower()
    is_placeholder = (
        not normalized
        or "todo" in normalized.lower()
        or parsed.scheme != "https"
        or not hostname
        or hostname in PLACEHOLDER_HOSTS
        or hostname.endswith(".example.com")
    )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    is_public_address = address is None or address.is_global
    if is_placeholder or not is_public_address:
        raise ManifestError(detail=f"invalid deployment target: {target!r}")


def assert_selected_tag(selected: str, approved: str) -> None:
    if selected != approved:
        raise ManifestError(detail=f"{selected!r} is not the approved release tag {approved!r}")


def assert_project_repositories(manifest: ReleaseManifest, project: str) -> None:
    expected = {
        service: f"ghcr.io/{project}/{repository}"
        for service, repository in SERVICE_REPOSITORIES.items()
    }
    actual = {
        "api": manifest.images.api.repository,
        "worker": manifest.images.worker.repository,
        "studio": manifest.images.studio.repository,
    }
    if actual != expected:
        raise ManifestError(detail=f"release image repository mismatch: expected {expected!r}, found {actual!r}")


def assert_contract_compatible(
    manifest: ReleaseManifest,
    running_schema: str,
    running_queue: str,
) -> None:
    if running_schema != manifest.schema_contract:
        raise ManifestError(
            detail=f"schema contract {running_schema!r} is incompatible with {manifest.schema_contract!r}",
        )
    if running_queue != manifest.queue_contract:
        raise ManifestError(
            detail=f"queue contract {running_queue!r} is incompatible with {manifest.queue_contract!r}",
        )


def _revision(output: str) -> str:
    matches = re.findall(r"(?m)^([0-9A-Za-z][0-9A-Za-z_-]*)\s*(?:\(head\))?\s*$", output.strip())
    if len(matches) != 1:
        raise ManifestError(detail=f"expected one Alembic revision, found {matches!r}")
    return matches[0]


def assert_database_revision(current: str, expected: str, heads: str | None = None) -> None:
    current_revision = _revision(current)
    expected_revision = _revision(expected)
    if current_revision != expected_revision:
        raise ManifestError(
            detail=f"database revision {current_revision!r} does not match release {expected_revision!r}",
        )
    if heads is not None and _revision(heads) != expected_revision:
        raise ManifestError(detail="selected release image Alembic head does not match its manifest")


def assert_database_revision_compatible(
    manifest: ReleaseManifest,
    current: str,
    compatible_revisions: str,
) -> None:
    current_revision = _revision(current)
    allowed_revisions = frozenset(revision.strip() for revision in compatible_revisions.split(",") if revision.strip())
    if manifest.db_revision not in allowed_revisions or current_revision not in allowed_revisions:
        raise ManifestError(
            detail=(
                f"database revisions {manifest.db_revision!r} and {current_revision!r} "
                "are not both allowed by the current schema policy"
            ),
        )


def assert_runtime_identity(manifest: ReleaseManifest, runtime: RuntimeIdentity) -> None:
    expected = RuntimeIdentity(
        api_source_sha=manifest.source_sha,
        worker_source_shas=[manifest.source_sha] * len(runtime.worker_source_shas),
        studio_source_sha=manifest.source_sha,
        api_digest=manifest.images.api.digest,
        worker_digest=manifest.images.worker.digest,
        studio_digest=manifest.images.studio.digest,
    )
    if runtime != expected:
        raise ManifestError(detail="running API, worker, and Studio do not match the approved release")


def _usage() -> ManifestError:
    return ManifestError(
        detail=(
            "usage: release_manifest.py validate MANIFEST [TAG SCHEMA QUEUE TARGET ...] | "
            "verify-db MANIFEST CURRENT [HEADS] | "
            "verify-db-compatible MANIFEST CURRENT COMPATIBLE_REVISIONS | "
            "verify-runtime MANIFEST RUNTIME_JSON"
        ),
    )


def run(arguments: list[str]) -> None:
    if len(arguments) < 2:
        raise _usage()
    command_text, manifest_path, *values = arguments
    command = Command(command_text)
    manifest = load_manifest(Path(manifest_path))
    match command:
        case Command.VALIDATE:
            if len(values) < 4:
                raise _usage()
            tag, schema, queue, project, *targets = values
            assert_selected_tag(tag, manifest.release_tag)
            assert_project_repositories(manifest, project)
            assert_contract_compatible(manifest, schema, queue)
            for target in targets:
                assert_deploy_target(target)
        case Command.VERIFY_DB:
            if len(values) not in {1, 2}:
                raise _usage()
            heads = values[1] if len(values) == 2 else None
            assert_database_revision(values[0], manifest.db_revision, heads)
        case Command.VERIFY_DB_COMPATIBLE:
            if len(values) != 2:
                raise _usage()
            assert_database_revision_compatible(manifest, values[0], values[1])
        case Command.VERIFY_RUNTIME:
            if len(values) != 1:
                raise _usage()
            assert_runtime_identity(manifest, RuntimeIdentity.model_validate_json(Path(values[0]).read_text()))
        case unreachable:
            assert_never(unreachable)


def main() -> int:
    try:
        run(sys.argv[1:])
    except (ValueError, ValidationError, OSError, json.JSONDecodeError) as error:
        print(f"release manifest validation failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
