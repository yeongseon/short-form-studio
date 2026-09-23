import os
from pathlib import Path
import subprocess

import pytest


def test_api_image_executes_lightweight_task_while_health_and_db_remain_responsive():
    image = os.getenv("LIGHTWEIGHT_TEST_IMAGE")
    database = os.getenv("FIRST_SHORT_TEST_DATABASE_URL")
    redis = os.getenv("FIRST_SHORT_TEST_REDIS_URL")
    if not image or not database or not redis:
        pytest.skip("Set LIGHTWEIGHT_TEST_IMAGE and FIRST_SHORT_TEST_DATABASE_URL/REDIS_URL")
    probe = Path(__file__).with_name("lightweight_image_probe.py").resolve()
    result = subprocess.run(
        ["docker", "run", "--rm", "--network", "host", "--entrypoint", "python",
         "-e", f"DATABASE_URL={database}", "-e", f"PROBE_REDIS_URL={redis}",
         "-e", "ARTIFACT_ROOT=/tmp/artifacts", "-e", "ENVIRONMENT=development",
         "-v", f"{probe}:/probe/lightweight_image_probe.py:ro",
         image, "/probe/lightweight_image_probe.py"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: image lightweight task" in result.stdout
