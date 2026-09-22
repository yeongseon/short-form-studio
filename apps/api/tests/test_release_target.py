"""Exercise release preparation only in a disposable project directory."""

import subprocess
import tomllib
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("suffix", ["", "-e2e"])
def test_release_keeps_package_version_when_tag_has_suffix(tmp_path: Path, suffix: str) -> None:
    # Given a sandbox with no repository, remotes, or real project metadata.
    (tmp_path / "Makefile").write_text((ROOT / "Makefile").read_text())
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname = "release-test"\nversion = "0.4.0"\n')

    # When preparing a release with an optional tag-only suffix.
    result = subprocess.run(
        ["make", "release", "VERSION=0.5.0", f"TAG_SUFFIX={suffix}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    # Then the package version stays valid and the suggested tag carries the suffix.
    assert result.returncode == 0, result.stderr
    assert tomllib.loads(project.read_text())["project"]["version"] == "0.5.0"
    assert f"git tag v0.5.0{suffix} &&" in result.stdout


def test_release_rejects_missing_version_before_writing(tmp_path: Path) -> None:
    # Given existing metadata in an isolated sandbox.
    (tmp_path / "Makefile").write_text((ROOT / "Makefile").read_text())
    project = tmp_path / "pyproject.toml"
    original = '[project]\nversion = "0.4.0"\n'
    project.write_text(original)

    # When VERSION is omitted, even with a suffix.
    result = subprocess.run(
        ["make", "release", "VERSION=", "TAG_SUFFIX=-e2e"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    # Then release preparation fails without modifying metadata.
    assert result.returncode != 0
    assert project.read_text() == original
