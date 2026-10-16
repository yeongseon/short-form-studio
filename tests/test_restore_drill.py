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

    # Then
    assert result.returncode == 0, result.stderr
    assert "RESTORE DRILL PASSED" in result.stdout
