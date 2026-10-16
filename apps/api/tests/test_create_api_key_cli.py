from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_create_api_key_offers_machine_readable_output() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "create_api_key.py"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--json" in result.stdout
