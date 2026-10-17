from __future__ import annotations

import json
import os
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
    assert "provider calls: 0" in result.stdout
    assert "production schema: migrated" in result.stdout
    assert "real API auth: owner=200 workspace-b=404 revoked=401 missing=401 timeline=200/404" in result.stdout
    assert "real API downloads: media=200 final-mp4=200 foreign=404 revoked=401 missing=401 checksum=verified ffprobe=verified" in result.stdout
    assert "post-restore render: restored Timeline image audio -> final.mp4" in result.stdout
    assert "provider guard: armed and untouched" in result.stdout
    assert "broker recovery: pending=failed queued=queued running=failed" in result.stdout
    evidence_line = next(
        line for line in result.stdout.splitlines() if line.startswith("RESTORE_EVIDENCE=")
    )
    evidence = json.loads(evidence_line.removeprefix("RESTORE_EVIDENCE="))
    assert evidence["restore_head_sha"] == os.environ["RESTORE_HEAD_SHA"]
    assert all("@sha256:" in digest for digest in evidence["release_image_digests"])
    assert evidence["credential_free"] is True
    assert evidence["phase_durations_seconds"]["total"] > 0
