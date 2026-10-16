from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from scripts.release_manifest import (
    ReleaseManifest,
    assert_contract_compatible,
    assert_database_revision,
    assert_deploy_target,
    assert_selected_tag,
)


ROOT = Path(__file__).resolve().parents[3]
DIGEST = "sha256:" + "a" * 64
SOURCE_SHA = "b" * 40


def manifest_data() -> dict[str, str | dict[str, str | dict[str, str]]]:
    return {
        "release_tag": "2026.10.16.1",
        "source_sha": SOURCE_SHA,
        "images": {
            "api": {"repository": "ghcr.io/acme/app/api", "digest": DIGEST},
            "worker": {"repository": "ghcr.io/acme/app/worker", "digest": DIGEST},
            "studio": {"repository": "ghcr.io/acme/app/studio-web", "digest": DIGEST},
        },
        "db_revision": "035_add_api_keys",
        "schema_contract": "1",
        "queue_contract": "1",
    }


@pytest.mark.parametrize(
    "target",
    [
        "",
        "TODO",
        "https://staging.example.com/api",
        "https://127.0.0.2/deploy",
        "https://10.0.0.1/deploy",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/deploy",
    ],
)
def test_deploy_target_rejects_placeholder_before_migration(target: str) -> None:
    # Given an unconfigured deployment target, when preflight validates it, then it stops.
    with pytest.raises(ValueError, match="deployment target"):
        assert_deploy_target(target)


@pytest.mark.parametrize("digest", ["", "sha256:abc", "a" * 64])
def test_manifest_rejects_missing_or_malformed_digest(digest: str) -> None:
    # Given a release with an invalid API identity.
    data = manifest_data()
    images = data["images"]
    assert isinstance(images, dict)
    api = images["api"]
    assert isinstance(api, dict)
    api["digest"] = digest

    # When parsed at the release boundary, then no manifest is produced.
    with pytest.raises(ValidationError):
        ReleaseManifest.model_validate(data)


@pytest.mark.parametrize("selected", ["latest", "main-deadbee", "does-not-exist"])
def test_selected_tag_rejects_arbitrary_or_unapproved_value(selected: str) -> None:
    # Given one approved immutable release tag, when another tag is selected, then it stops.
    with pytest.raises(ValueError, match="approved release tag"):
        assert_selected_tag(selected, "2026.10.16.1")


def test_schema_incompatibility_stops_release() -> None:
    # Given a running schema newer than the selected release supports.
    manifest = ReleaseManifest.model_validate(manifest_data())

    # When compatibility is checked, then preflight rejects the release.
    with pytest.raises(ValueError, match="schema contract"):
        assert_contract_compatible(manifest, running_schema="2", running_queue="1")


def test_database_revision_mismatch_is_failure() -> None:
    # Given different live and manifest revisions, when compared, then verification fails.
    with pytest.raises(ValueError, match="database revision"):
        assert_database_revision(current="034", expected="035")


def test_revision_cli_returns_nonzero_on_mismatch(tmp_path: Path) -> None:
    # Given a valid selected manifest on disk.
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps(manifest_data()))

    # When the live Alembic revision differs from its bound revision.
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/release_manifest.py"), "verify-db", str(manifest), "034"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Then the command is automation-safe and returns failure.
    assert result.returncode != 0

