from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "restore_drill.py"


def test_disposable_restore_drill() -> None:
    # Given
    if shutil.which("docker") is None:
        pytest.skip("docker is required for the disposable restore drill")

    # When
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )
    print(result.stdout, end="")

    # Then
    assert result.returncode == 0, result.stderr
    assert "RESTORE DRILL PASSED" in result.stdout
    assert "A/B isolation: owner=200 cross-workspace=404" in result.stdout
    assert "revoked key: rejected" in result.stdout
    assert "protected downloads: media=200 final-mp4=200" in result.stdout
    assert "protected download checksum: verified" in result.stdout
    assert "provider calls: 0" in result.stdout
    assert "production schema: migrated" in result.stdout
    assert "real API auth: owner=200 workspace-b=404 revoked=401 missing=401" in result.stdout
    assert "real API downloads: media=200 final-mp4=200 checksum=verified ffprobe=verified" in result.stdout
    assert "provider guard: armed and untouched" in result.stdout
