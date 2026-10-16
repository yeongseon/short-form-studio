from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

from billiard.exceptions import SoftTimeLimitExceeded

from celery_app import celery_app
from celery_app import is_shutting_down


broker_root = os.getenv("WORKER_TOPOLOGY_BROKER_DIR")
if broker_root:
    root = Path(broker_root)
    celery_app.conf.broker_transport_options = {
        "data_folder_in": str(root / "queue"),
        "data_folder_out": str(root / "queue"),
        "control_folder": str(root / "control"),
    }
    celery_app.conf.result_backend = "cache+memory://"


def _write_state(path: str, **state: str | int | bool) -> None:
    destination = Path(path)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(destination)


def _stop_child(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is not None:
        return
    child.send_signal(signal.SIGTERM)
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait(timeout=2)


@celery_app.task(name="worker_topology.cooperative")
def cooperative(state_path: str, provider_url: str, work_dir: str) -> None:
    state = Path(state_path)
    workspace = Path(work_dir)
    workspace.mkdir(parents=True)
    partial = workspace / "partial.media"
    quota = workspace / "quota.reserved"
    partial.write_bytes(b"partial")
    quota.write_text("reserved", encoding="utf-8")
    child = subprocess.Popen(["sleep", "300"])
    _write_state(state_path, status="running", child_pid=child.pid)
    try:
        with urlopen(f"{provider_url}/call", timeout=5) as response:
            response.read()
        _write_state(state_path, status="provider_done", child_pid=child.pid)
        while True:
            current = json.loads(state.read_text(encoding="utf-8"))
            if current.get("cancel_requested") is True or is_shutting_down():
                _write_state(state_path, status="cancelled", child_pid=child.pid)
                return
            time.sleep(0.05)
    finally:
        _stop_child(child)
        partial.unlink(missing_ok=True)
        quota.unlink(missing_ok=True)


@celery_app.task(name="worker_topology.deadline")
def deadline(state_path: str, work_dir: str) -> None:
    workspace = Path(work_dir)
    workspace.mkdir(parents=True)
    partial = workspace / "partial.media"
    quota = workspace / "quota.reserved"
    partial.write_bytes(b"partial")
    quota.write_text("reserved", encoding="utf-8")
    child = subprocess.Popen(["sleep", "300"])
    _write_state(state_path, status="running", child_pid=child.pid)
    try:
        while True:
            time.sleep(0.1)
    except SoftTimeLimitExceeded:
        _write_state(state_path, status="failed_timeout", child_pid=child.pid)
        raise
    finally:
        _stop_child(child)
        partial.unlink(missing_ok=True)
        quota.unlink(missing_ok=True)


@celery_app.task(name="worker_topology.attempt")
def attempt(state_path: str, attempt_id: str) -> None:
    state = Path(state_path)
    current = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {}
    if current.get("active_attempt") != attempt_id:
        return
    _write_state(state_path, active_attempt=attempt_id, status="success")
