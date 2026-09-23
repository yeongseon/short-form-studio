"""Production packages obey ADR001 without baselines or exemptions."""

from pathlib import Path
import subprocess
import sys


def test_production_packages_have_only_downward_dependencies() -> None:
    # Given the real production source tree (not checker fixtures).
    root = Path(__file__).resolve().parents[1]
    # When the same gate used by CI scans it.
    result = subprocess.run(
        [sys.executable, str(root / "scripts/check_package_dependencies.py")],
        capture_output=True, text=True, check=False,
    )
    # Then every dependency is legal.
    assert result.returncode == 0, result.stdout + result.stderr
