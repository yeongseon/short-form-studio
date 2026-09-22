"""Execute static Compose validation without relying on a developer's .env."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[3]


def test_smoke_runs_in_a_fresh_checkout_without_creating_dotenv(tmp_path: Path) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is needed for the executable config check")
    files = (
        ".env.example",
        "docker-compose.yml",
        "scripts/quickstart_smoke.sh",
        "scripts/create_api_key.py",
        "apps/api/alembic.ini",
        "apps/studio-web/nginx.conf.template",
        "docs/QUICKSTART.md",
    )
    for name in files:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)

    result = subprocess.run(
        ["bash", "scripts/quickstart_smoke.sh"],
        cwd=tmp_path,
        env={"PATH": os.defpath, "HOME": str(tmp_path), "TMPDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (tmp_path / ".env").exists()
    assert not list(tmp_path.glob("quickstart-smoke.*"))
