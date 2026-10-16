from __future__ import annotations

import json
import hashlib
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
from urllib.request import Request, urlopen

import anyio
import asyncpg
import pytest


EVIDENCE = Path(os.getenv("WORKER_TOPOLOGY_EVIDENCE_DIR", "/tmp/worker-topology-runtime"))
IMAGE = os.getenv("WORKER_TOPOLOGY_IMAGE", "worker-topology-image")
DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")
type ProbeMode = Literal["complete", "cooperative", "ffmpeg_hang", "redelivery", "wait"]
API_KEY = "topology-runtime-key"
API_URL = "http://127.0.0.1:58064"


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


def _container_ffmpeg_host_pid(name: str) -> int:
    output = _docker("top", name, "-eo", "pid,comm").stdout.splitlines()
    ffmpeg = [line.split()[0] for line in output[1:] if line.split()[-1] == "ffmpeg"]
    assert len(ffmpeg) == 1
    return int(ffmpeg[0])


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
        args=[run_id, mode, state.name, provider_url],
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
        "-e", "WORKER_TOPOLOGY_PROBE_ENABLED=1",
        "-e", "WORKER_TOPOLOGY_EVIDENCE_DIR=/evidence",
        "-e", f"WORKER_TOPOLOGY_PROVIDER_URL={os.environ['TOPOLOGY_PROVIDER_URL']}",
        "--add-host", "host.docker.internal:host-gateway",
        "-v", f"{EVIDENCE}:/evidence",
        IMAGE,
    ]
    if command is not None:
        args.extend(command)
    _docker(*args)
    time.sleep(3)
    assert _docker("inspect", "-f", "{{.State.Running}}", name).stdout.strip() == "true"


def _stop_run(run_id: int) -> None:
    request = Request(
        f"{API_URL}/api/creator/runs/{run_id}/stop",
        method="POST",
        headers={"X-API-Key": API_KEY},
    )
    with urlopen(request, timeout=10) as response:
        assert response.status == 200


async def _snapshot(run_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        run = await connection.fetchrow("SELECT id, status, current_stage FROM creator_runs WHERE id=$1", run_id)
        tasks = await connection.fetch(
            "SELECT celery_task_id, status, attempt, claim_token FROM creator_run_tasks WHERE run_id=$1 ORDER BY id",
            run_id,
        )
        quota = await connection.fetch(
            "SELECT owner_id, status, operation_type FROM workspace_quota_reservation_owners "
            "WHERE owner_id IN (SELECT celery_task_id FROM creator_run_tasks WHERE run_id=$1) ORDER BY owner_id",
            run_id,
        )
        return {"run": dict(run) if run else None, "tasks": [dict(row) for row in tasks], "quota": [dict(row) for row in quota]}
    finally:
        await connection.close()


def _persist_snapshot(name: str, run_id: int, **fields: object) -> None:
    state = anyio.run(_snapshot, run_id)
    (EVIDENCE / name).write_text(json.dumps({**state, **fields}, default=str), encoding="utf-8")


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
    anyio.run(
        _sql,
        "TRUNCATE creator_media_assets, creator_artifacts, workspace_quota_reservation_owners, "
        "workspace_quota_reservations, creator_run_tasks, creator_runs, creator_projects, "
        "workspace_members, api_keys, workspaces, users CASCADE",
    )
    anyio.run(
        _sql,
        """INSERT INTO users(id, auth_subject) VALUES(1, 'topology');
        INSERT INTO workspaces(id, name, slug, owner_id) VALUES(1, 'Topology', 'topology', 1);
        INSERT INTO workspace_members(workspace_id, user_id, role) VALUES(1, 1, 'owner');
        INSERT INTO creator_projects(id, title, source_type, status, workspace_id)
        VALUES(1, 'Topology', 'idea', 'active', 1);""",
    )
    anyio.run(
        _sql,
        "INSERT INTO api_keys(user_id, key_hash, name) VALUES(1, $1, 'topology-runtime')",
        (hashlib.sha256(API_KEY.encode()).hexdigest(),),
    )
    gateway = _docker("network", "inspect", "worker-topology", "-f", "{{(index .IPAM.Config 0).Gateway}}").stdout.strip()
    server = ThreadingHTTPServer((gateway, 0), _Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["TOPOLOGY_PROVIDER_URL"] = f"http://{gateway}:{server.server_port}"
    api_environment = os.environ | {
        "DATABASE_URL": DATABASE_URL,
        "REDIS_URL": REDIS_URL,
        "ENVIRONMENT": "test",
    }
    api = subprocess.Popen(
        ["python3", "-m", "uvicorn", "shorts_api.main:app", "--host", "127.0.0.1", "--port", "58064"],
        env=api_environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{API_URL}/healthz", timeout=1):
                break
        except OSError:
            time.sleep(0.1)
    else:
        pytest.fail("topology API did not start")
    try:
        yield
    finally:
        api.terminate()
        api.wait(timeout=5)
        server.shutdown()
        thread.join(timeout=2)
        for name in (
            "topology-solo-cancel", "topology-scaled-redelivery", "topology-scaled-redelivered",
            "topology-scaled-timeout", "topology-scaled-ffmpeg", "topology-scaled-replacement",
        ):
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
    _Provider.calls = 0
    _worker("topology-solo-cancel")
    blocked = EVIDENCE / "blocked.json"
    successor = EVIDENCE / "successor.json"
    anyio.run(
        _sql,
        """INSERT INTO workspace_quota_reservations(workspace_id, period_start, image_count)
        VALUES(1, date_trunc('month', now()), 1);
        INSERT INTO workspace_quota_reservation_owners(owner_id, workspace_id, period_start, operation_type, status)
        VALUES('blocked-delivery', 1, date_trunc('month', now()), 'image_gen', 'reserved');""",
    )

    # When a long production task owns the worker and successor work is queued.
    _send(101, "blocked-delivery", "cooperative", blocked, provider_url=os.environ["TOPOLOGY_PROVIDER_URL"])
    _wait_state(blocked, "provider_done")
    started = time.monotonic()
    _send(102, "successor-delivery", "complete", successor)
    time.sleep(1)
    assert not successor.exists()
    _stop_run(101)
    cancelled = _wait_state(blocked, "cancelled")
    _wait_state(successor, "completed")
    delay = time.monotonic() - started

    # Then Postgres owns the claims and cancellation prevents new provider or persistence work.
    first = _wait_task("successor-delivery", "success")
    quota = anyio.run(_row, "SELECT status FROM workspace_quota_reservation_owners WHERE owner_id='blocked-delivery'")
    reservation = anyio.run(_row, "SELECT image_count FROM workspace_quota_reservations WHERE workspace_id=1")
    artifact_rows = anyio.run(_row, "SELECT count(*) AS count FROM creator_artifacts WHERE run_id=101")
    media_rows = anyio.run(_row, "SELECT count(*) AS count FROM creator_media_assets WHERE run_id=101")
    storage = EVIDENCE / "storage" / "101"
    storage_entries = list(storage.rglob("*")) if storage.exists() else []
    provider_calls = _Provider.calls
    assert first["attempt"] == 1
    assert quota is not None and quota["status"] == "cancelled"
    assert reservation is not None and reservation["image_count"] == 0
    assert artifact_rows is not None and artifact_rows["count"] == 0
    assert media_rows is not None and media_rows["count"] == 0
    assert provider_calls == 1
    assert storage_entries == []
    assert cancelled["second_boundary_suppressed"] is True
    (EVIDENCE / "fairness.json").write_text(json.dumps({"successor_delay_seconds": delay}), encoding="utf-8")
    _persist_snapshot(
        "cancellation-final-state.json", 101, provider_calls=provider_calls,
        artifact_rows=artifact_rows["count"], media_asset_rows=media_rows["count"],
        storage_entries=[str(path) for path in storage_entries],
    )


def test_prefork_hard_timeout_and_ffmpeg_child_die_with_worker() -> None:
    # Given the shipped image running the production prefork queue command.
    _new_run(103)
    _new_run(104)
    command = ['celery', '-A', 'celery_app.celery_app', 'worker', '--loglevel=info', '--pool=prefork', '--concurrency=2', '-Q', 'image']
    _worker("topology-scaled-redelivery", command)
    redelivery_state = EVIDENCE / "active-redelivery.json"
    timeout_state = EVIDENCE / "timeout.json"
    ffmpeg_state = EVIDENCE / "ffmpeg.json"

    # When a claimed delivery loses its worker, the broker redelivers it to the exact scaled command.
    _send(103, "active-redelivery", "redelivery", redelivery_state, queue="image")
    _wait_state(redelivery_state, "claimed")
    first_claim = _wait_task("active-redelivery", "running")
    _docker("kill", "--signal=KILL", "topology-scaled-redelivery")
    anyio.run(
        _sql,
        "UPDATE creator_run_tasks SET status='failed', finished_at=NOW() "
        "WHERE celery_task_id='active-redelivery' AND claim_token=$1 AND status='running'",
        (first_claim["claim_token"],),
    )
    _worker("topology-scaled-redelivered", command)
    _wait_state(redelivery_state, "redelivered")
    redelivered = _wait_task("active-redelivery", "running")
    assert redelivered["attempt"] == first_claim["attempt"]
    assert redelivered["claim_token"] != first_claim["claim_token"]
    stale_update = anyio.run(
        _sql,
        "UPDATE creator_run_tasks SET status='success' WHERE celery_task_id='active-redelivery' AND claim_token=$1",
        (first_claim["claim_token"],),
    )
    assert stale_update == "UPDATE 0"
    _stop_run(103)
    _wait_state(redelivery_state, "cancelled")
    _persist_snapshot("redelivery-final-state.json", 103)

    _new_run(106)
    _send(106, "timeout-delivery", "wait", timeout_state, queue="image", time_limit=2)
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
    _persist_snapshot("timeout-final-state.json", 106)
    _capture_worker("topology-scaled-redelivered")
    _docker("rm", "-f", "topology-scaled-redelivered")
    _worker("topology-scaled-ffmpeg", command)
    _send(104, "ffmpeg-delivery", "ffmpeg_hang", ffmpeg_state, queue="image")
    state = _wait_state(ffmpeg_state, "ffmpeg_running")
    host_pid = _container_ffmpeg_host_pid("topology-scaled-ffmpeg")
    _docker("kill", "--signal=TERM", "topology-scaled-ffmpeg")
    time.sleep(1)
    _docker("kill", "--signal=KILL", "topology-scaled-ffmpeg", check=False)
    _capture_worker("topology-scaled-ffmpeg")
    anyio.run(_sql, "UPDATE creator_runs SET status='cancelled' WHERE id=104")

    # Then forced worker loss removes the real FFmpeg child and a replacement can start.
    assert _docker("inspect", "-f", "{{.State.Running}}", "topology-scaled-ffmpeg").stdout.strip() == "false"
    assert not Path(f"/proc/{host_pid}").exists()
    _worker("topology-scaled-replacement", command)
    _new_run(105)
    replacement = EVIDENCE / "replacement.json"
    _send(105, "replacement-delivery", "complete", replacement, queue="image")
    _wait_state(replacement, "completed")
    (EVIDENCE / "ffmpeg-cleanup.json").write_text(
        json.dumps({"container_pid": state["child_pid"], "host_pid": host_pid, "container_running": False}), encoding="utf-8",
    )
