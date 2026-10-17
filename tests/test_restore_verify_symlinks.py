from __future__ import annotations

import subprocess
import sys
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_verify.py"


@pytest.fixture(autouse=True)
def _accept_synthetic_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_RESTORE", "/usr/bin/true")


@pytest.mark.parametrize(
    "symlink_kind",
    ["bundle", "manifest", "database", "media-root", "nested-directory", "media-file"],
)
def test_verifier_rejects_every_symlink_boundary(
    tmp_path: Path, symlink_kind: str
) -> None:
    # Given
    bundle = _bundle(tmp_path)
    assert _run("create", bundle).returncode == 0
    outside = tmp_path / "outside"
    outside.mkdir()
    selected_bundle = bundle

    match symlink_kind:
        case "bundle":
            selected_bundle = tmp_path / "bundle-link"
            selected_bundle.symlink_to(bundle, target_is_directory=True)
        case "manifest":
            external = outside / "manifest.json"
            external.write_bytes((bundle / "manifest.json").read_bytes())
            (bundle / "manifest.json").unlink()
            (bundle / "manifest.json").symlink_to(external)
        case "database":
            external = outside / "database.dump"
            external.write_bytes((bundle / "database.dump").read_bytes())
            (bundle / "database.dump").unlink()
            (bundle / "database.dump").symlink_to(external)
        case "media-root":
            external = outside / "media"
            (bundle / "media").rename(external)
            (bundle / "media").symlink_to(external, target_is_directory=True)
        case "nested-directory":
            external = outside / "workspace-a"
            (bundle / "media/workspace-a").rename(external)
            (bundle / "media/workspace-a").symlink_to(
                external, target_is_directory=True
            )
        case "media-file":
            external = outside / "image.png"
            external.write_bytes((bundle / "media/workspace-a/image.png").read_bytes())
            (bundle / "media/workspace-a/image.png").unlink()
            (bundle / "media/workspace-a/image.png").symlink_to(external)
        case unexpected:
            pytest.fail(f"unexpected test case: {unexpected}")

    # When
    result = _run("verify", selected_bundle)

    # Then
    assert result.returncode != 0
    assert "symlink" in result.stderr.lower()


def test_create_manifest_bundle_swap_does_not_redirect_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Given
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    specification = importlib.util.spec_from_file_location("restore_verify", SCRIPT)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    bundle = _bundle(tmp_path)
    moved_bundle = tmp_path / "moved-bundle"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_open = module.os.open

    def swap_bundle(
        path: str | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if Path(path).name.startswith(".manifest."):
            bundle.rename(moved_bundle)
            bundle.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(module.os, "open", swap_bundle)
    arguments = module.parser().parse_args(
        [
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
        ]
    )

    # When
    module.create_manifest(arguments)

    # Then
    assert list(outside.iterdir()) == []
    assert (moved_bundle / "manifest.json").is_file()


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bundle"
    media = bundle / "media/workspace-a"
    media.mkdir(parents=True)
    (bundle / "database.dump").write_bytes(b"PGDMP synthetic database")
    (media / "image.png").write_bytes(b"synthetic image")
    return bundle


def _run(command: str, bundle: Path) -> subprocess.CompletedProcess[str]:
    arguments = [sys.executable, str(SCRIPT), command, str(bundle)]
    if command == "create":
        arguments.extend(
            [
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
            ]
        )
    else:
        arguments.extend(
            [
                "--expected-alembic-revision",
                "revision-1",
                "--expected-secret-fingerprint",
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            ]
        )
    return subprocess.run(arguments, capture_output=True, text=True, check=False)
