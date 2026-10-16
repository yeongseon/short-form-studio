from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Literal

import anyio
import asyncpg
import pytest


EVIDENCE = Path(os.getenv("WORKER_TOPOLOGY_EVIDENCE_DIR", "/tmp/worker-topology-runtime"))
IMAGE = os.getenv("WORKER_TOPOLOGY_IMAGE", "worker-topology-image")
DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")
type ProbeMode = Literal["complete", "cooperative", "ffmpeg_hang", "wait"]


class _Provider(BaseHTTPRequestHandler):
    calls = 0

    def do_GET(self) -> None:
        type(self).calls += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        _ = (format, args)


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], check=check, capture_output=True, text=True, timeout=60,
    )


async def _sql(statement: str, args: tuple[str | int, ...] = ()) -> str:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        return await connection.execute(statement, *args)
    finally:
        await connection.close()


async def _row(statement: str, args: tuple[str | int, ...] = ()) -> asyncpg.Record | None:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        return await connection.fetchrow(statement, *args)
    finally:
        await connection.close()


def _wait_state(path: Path, status: str, timeout: float = 30) -> dict[str, str | int | float | bool]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("status") == status:
                return state
        time.sleep(0.1)
    pytest.fail(f"timed out waiting for {status}: {path.read_text() if path.exists() else 'missing'}")


def _wait_task(task_id: str, status: str, timeout: float = 30) -> asyncpg.Record:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = anyio.run(
            _row,
            "SELECT status, attempt, claim_token FROM creator_run_tasks WHERE celery_task_id=$1",
            (task_id,),
        )
        if row is not None and row["status"] == status:
            return row
        time.sleep(0.1)
    pytest.fail(f"timed out waiting for task {task_id}={status}")


def _process_exists(pid: int) -> bool:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "comm="],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.returncode == 0 and result.stdout.strip() == "ffmpeg"


def _redis_available() -> bool:
    _, address = REDIS_URL.split("//", maxsplit=1)
    host_port = address.split("/", maxsplit=1)[0]
    host, port = host_port.split(":", maxsplit=1)
    try:
        with socket.create_connection((host, int(port)), timeout=1):
            return True
    except OSError:
        return False


def _send(
    run_id: int,
    task_id: str,
    mode: ProbeMode,
    state: Path,
    *,
    provider_url: str = "",
    queue: str = "creator",
    time_limit: int | None = None,
) -> None:
    from celery_app import celery_app

    delivery_options = {"time_limit": time_limit} if time_limit is not None else {}
    celery_app.send_task(
        "runtime_topology.probe",
        args=[run_id, mode, f"/evidence/{state.name}", provider_url],
        task_id=task_id,
        queue=queue,
        **delivery_options,
    )


def _worker(name: str, command: list[str] | None = None) -> None:
    args = [
        "run", "-d", "--name", name, "--network", "worker-topology",
        "-e", "DATABASE_URL=postgresql://review:review-local-only@topology-postgres:5432/topology",
        "-e", "REDIS_URL=redis://topology-redis:6379/0",
        "-e", "ENVIRONMENT=test",
        "--add-host", "host.docker.internal:host-gateway",
        "-v", f"{EVIDENCE}:/evidence",
        IMAGE,
    ]
    if command is not None:
        args.extend(command)
    _docker(*args)
    time.sleep(3)
    assert _docker("inspect", "-f", "{{.State.Running}}", name).stdout.strip() == "true"


def _capture_worker(name: str) -> None:
    logs = _docker("logs", name, check=False)
    if logs.returncode != 0:
        return
    (EVIDENCE / f"{name}.worker.log").write_text(
        logs.stdout + logs.stderr,
        encoding="utf-8",
    )


@pytest.fixture(scope="module", autouse=True)
def runtime() -> Iterator[None]:
    if not DATABASE_URL or not REDIS_URL or not shutil.which("docker"):
        pytest.skip("runtime image environment unavailable")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    anyio.run(_sql, "TRUNCATE creator_run_tasks, creator_runs, creator_projects, workspace_members, workspaces, users CASCADE")
    anyio.run(
        _sql,
        """INSERT INTO users(id, auth_subject) VALUES(1, 'topology');
        INSERT INTO workspaces(id, name, slug, owner_id) VALUES(1, 'Topology', 'topology', 1);
        INSERT INTO workspace_members(workspace_id, user_id, role) VALUES(1, 1, 'owner');
        INSERT INTO creator_projects(id, title, source_type, status, workspace_id)
        VALUES(1, 'Topology', 'idea', 'active', 1);""",
    )
    server = ThreadingHTTPServer(("0.0.0.0", 0), _Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["TOPOLOGY_PROVIDER_URL"] = f"http://host.docker.internal:{server.server_port}"
    try:
        yield
    finally:
        server.shutdown()
        thread.join(timeout=2)
        for name in ("topology-worker", "topology-prefork", "topology-prefork-replacement"):
            _capture_worker(name)
            _docker("rm", "-f", name, check=False)


def _new_run(run_id: int) -> None:
    anyio.run(
        _sql,
        """INSERT INTO creator_runs(id, project_id, workspace_id, current_stage, status)
        VALUES($1, 1, 1, 'RENDER_GENERATING', 'running')""",
        (run_id,),
    )


def test_shipped_image_runs_production_claims_redelivery_and_fairness() -> None:
    # Given the shipped image using its default production entrypoint and solo command.
    _new_run(101)
    _new_run(102)
    _worker("topology-worker")
    blocked = EVIDENCE / "blocked.json"
    successor = EVIDENCE / "successor.json"

    # When a long production task owns the worker and successor work is queued.
    _send(101, "blocked-delivery", "cooperative", blocked, provider_url=os.environ["TOPOLOGY_PROVIDER_URL"])
    _wait_state(blocked, "provider_done")
    started = time.monotonic()
    _send(102, "successor-delivery", "complete", successor)
    time.sleep(1)
    assert not successor.exists()
    anyio.run(_sql, "UPDATE creator_runs SET status='cancelled' WHERE id=101")
    _wait_state(blocked, "cancelled")
    _wait_state(successor, "completed")
    delay = time.monotonic() - started

    # Then Postgres owns the claims, queue delay is measured, and stale redelivery is fenced.
    first = _wait_task("successor-delivery", "success")
    _send(102, "successor-delivery", "complete", successor)
    time.sleep(1)
    second = _wait_task("successor-delivery", "success")
    assert first["attempt"] == second["attempt"] == 1
    assert second["claim_token"] is None
    (EVIDENCE / "fairness.json").write_text(json.dumps({"successor_delay_seconds": delay}), encoding="utf-8")


def test_prefork_hard_timeout_and_ffmpeg_child_die_with_worker() -> None:
    # Given the shipped image running the production prefork queue command.
    _new_run(103)
    _new_run(104)
    command = [
        "celery", "-A", "celery_app.celery_app", "worker", "--loglevel=info",
        "--pool=prefork", "--concurrency=1", "-Q", "image",
    ]
    _worker("topology-prefork", command)
    timeout_state = EVIDENCE / "timeout.json"
    ffmpeg_state = EVIDENCE / "ffmpeg.json"

    # When a delivery exceeds its hard deadline, then the broker is lost and restored.
    _send(103, "timeout-delivery", "wait", timeout_state, queue="image", time_limit=2)
    _wait_state(timeout_state, "running")
    _wait_task("timeout-delivery", "failed")
    _docker("stop", "topology-redis")
    time.sleep(1)
    assert not _redis_available()
    _docker("start", "topology-redis")
    deadline = time.monotonic() + 10
    while not _redis_available() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _redis_available()
    _capture_worker("topology-prefork")
    _docker("rm", "-f", "topology-prefork")
    _worker("topology-prefork", command)
    _send(104, "ffmpeg-delivery", "ffmpeg_hang", ffmpeg_state, queue="image")
    state = _wait_state(ffmpeg_state, "ffmpeg_running")
    _docker("kill", "--signal=TERM", "topology-prefork")
    time.sleep(1)
    _docker("kill", "--signal=KILL", "topology-prefork", check=False)
    _capture_worker("topology-prefork")
    anyio.run(_sql, "UPDATE creator_runs SET status='cancelled' WHERE id=104")

    # Then forced worker loss removes the real FFmpeg child and a replacement can start.
    assert _docker("inspect", "-f", "{{.State.Running}}", "topology-prefork").stdout.strip() == "false"
    assert not _process_exists(int(state["child_pid"]))
    _worker("topology-prefork-replacement", command)
    _new_run(105)
    replacement = EVIDENCE / "replacement.json"
    _send(105, "replacement-delivery", "complete", replacement, queue="image")
    _wait_state(replacement, "completed")
    (EVIDENCE / "ffmpeg-cleanup.json").write_text(
        json.dumps({"child_pid": state["child_pid"], "container_running": False}), encoding="utf-8",
    )
