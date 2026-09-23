"""Run the real dev healthcheck suite from a dotenv-free checkout."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[3]


def test_healthcheck_fixture_ignores_host_environment_in_clean_checkout(tmp_path: Path) -> None:
    # Given only shipped inputs, no private dotenv, and invalid host interpolation.
    for name in (
        ".env.example",
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "apps/api/tests/test_dev_healthcheck.py",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)

    # When pytest resolves actual Compose config and executes the shipped Node probe.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "apps/api/tests/test_dev_healthcheck.py", "-q"],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "MAX_MEMORY_MB": "invalid-host-memory",
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    # Then all four real probe cases pass without creating a checkout dotenv.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout
    assert not (tmp_path / ".env").exists()
