from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler
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
API_KEY = "topology-runtime-key"
API_URL = "http://127.0.0.1:58064"
type ProbeMode = Literal[
    "cancellation_gate", "complete", "ffmpeg_hang", "redelivery",
    "timeout_resources", "wait"
]
SCALED_IMAGE_COMMAND = [
    "celery",
    "-A",
    "celery_app.celery_app",
    "worker",
    "--loglevel=info",
    "--pool=prefork",
    "--concurrency=2",
    "-Q",
    "image",
]


class Provider(BaseHTTPRequestHandler):
    calls = 0
    image_calls = 0
    image_release = threading.Event()

    def do_GET(self) -> None:
        type(self).calls += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self) -> None:
        type(self).image_calls += 1
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).image_release.wait(timeout=30)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        _ = (format, args)


def docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=60,
    )


async def sql(statement: str, args: tuple[str | int, ...] = ()) -> str:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        return await connection.execute(statement, *args)
    finally:
        await connection.close()


async def row(statement: str, args: tuple[str | int, ...] = ()) -> asyncpg.Record | None:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        return await connection.fetchrow(statement, *args)
    finally:
        await connection.close()


def initialize_database() -> None:
    anyio.run(
        sql,
        "TRUNCATE creator_media_assets, creator_artifacts, workspace_quota_reservation_owners, "
        "workspace_quota_reservations, creator_run_tasks, creator_runs, creator_projects, "
        "workspace_members, api_keys, workspaces, users CASCADE",
    )
    anyio.run(
        sql,
        """INSERT INTO users(id, auth_subject) VALUES(1, 'topology');
        INSERT INTO workspaces(id, name, slug, owner_id) VALUES(1, 'Topology', 'topology', 1);
        INSERT INTO workspace_members(workspace_id, user_id, role) VALUES(1, 1, 'owner');
        INSERT INTO creator_projects(id, title, source_type, status, workspace_id)
        VALUES(1, 'Topology', 'idea', 'active', 1);""",
    )
    anyio.run(
        sql,
        "INSERT INTO api_keys(user_id, key_hash, name) VALUES(1, $1, 'topology-runtime')",
        (hashlib.sha256(API_KEY.encode()).hexdigest(),),
    )


def new_run(run_id: int) -> None:
    anyio.run(
        sql,
        "INSERT INTO creator_runs(id, project_id, workspace_id, current_stage, status) "
        "VALUES($1, 1, 1, 'RENDER_GENERATING', 'running')",
        (run_id,),
    )


def wait_state(path: Path, status: str, timeout: float = 30) -> dict[str, str | int | float | bool]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
            if state.get("status") == status:
                return state
        time.sleep(0.1)
    pytest.fail(
        f"timed out waiting for {status}: {path.read_text() if path.exists() else 'missing'}"
    )


def wait_task(task_id: str, status: str, timeout: float = 30) -> asyncpg.Record:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = anyio.run(
            row,
            "SELECT status, attempt, claim_token FROM creator_run_tasks WHERE celery_task_id=$1",
            (task_id,),
        )
        if task is not None and task["status"] == status:
            return task
        time.sleep(0.1)
    pytest.fail(f"timed out waiting for task {task_id}={status}")


def container_process_host_pid(name: str, process_name: str) -> int:
    output = docker("top", name, "-eo", "pid,comm").stdout.splitlines()
    process = [line.split()[0] for line in output[1:] if line.split()[-1] == process_name]
    assert len(process) == 1
    return int(process[0])


def container_ffmpeg_host_pid(name: str) -> int:
    return container_process_host_pid(name, "ffmpeg")


def wait_host_process_exit(pid: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    process = Path(f"/proc/{pid}")
    while process.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not process.exists()


def redis_available() -> bool:
    _, address = REDIS_URL.split("//", maxsplit=1)
    host_port = address.split("/", maxsplit=1)[0]
    host, port = host_port.split(":", maxsplit=1)
    try:
        with socket.create_connection((host, int(port)), timeout=1):
            return True
    except OSError:
        return False


async def recover_lost_claim(task_id: str) -> None:
    from creator_service.task_tracking_service import task_tracking_service

    recovered = await task_tracking_service.mark_failed_if_running(
        task_id,
        "WORKER_LOST",
        "The active prefork delivery lost its worker process",
    )
    assert recovered is not None


def send_delayed_failure(task_id: str, claim_token: str) -> None:
    from celery.signals import task_failure

    class Sender:
        name = "runtime_topology.probe"
        max_retries = 0

        class Request:
            retries = 0

        request = Request()

    sender = Sender()
    sender.request.claim_token = claim_token
    task_failure.send(
        sender=sender,
        task_id=task_id,
        exception=RuntimeError("delayed old-delivery failure"),
    )


def send(
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


def send_scene_image(run_id: int, task_id: str, *, time_limit: int) -> None:
    from celery_app import celery_app

    celery_app.send_task(
        "generate_scene_image",
        args=[run_id, "scene-timeout", "sd15"],
        task_id=task_id,
        queue="image",
        time_limit=time_limit,
    )


def worker(name: str, command: list[str] | None = None) -> None:
    args = [
        "run",
        "-d",
        "--init",
        "--name",
        name,
        "--network",
        "worker-topology",
        "-e",
        "DATABASE_URL=postgresql://review:review-local-only@topology-postgres:5432/topology",
        "-e",
        "REDIS_URL=redis://topology-redis:6379/0",
        "-e",
        "ENVIRONMENT=test",
        "-e",
        "WORKER_TOPOLOGY_PROBE_ENABLED=1",
        "-e",
        "WORKER_TOPOLOGY_EVIDENCE_DIR=/evidence",
        "-e",
        f"WORKER_TOPOLOGY_PROVIDER_URL={os.environ['TOPOLOGY_PROVIDER_URL']}",
        "-e",
        f"STABLE_DIFFUSION_BASE_URL={os.environ['TOPOLOGY_PROVIDER_URL']}",
        "-e",
        "ARTIFACT_ROOT=/evidence/storage",
        "-v",
        f"{EVIDENCE}:/evidence",
        IMAGE,
    ]
    if command is not None:
        args.extend(command)
    docker(*args)
    time.sleep(3)
    assert docker("inspect", "-f", "{{.State.Running}}", name).stdout.strip() == "true"


def stop_run(run_id: int) -> None:
    request = Request(
        f"{API_URL}/api/creator/runs/{run_id}/stop",
        method="POST",
        headers={"X-API-Key": API_KEY},
    )
    with urlopen(request, timeout=10) as response:
        assert response.status == 200


async def snapshot(run_id: int) -> dict[str, object]:
    connection = await asyncpg.connect(DATABASE_URL)
    try:
        run = await connection.fetchrow(
            "SELECT id, status, current_stage FROM creator_runs WHERE id=$1", run_id
        )
        tasks = await connection.fetch(
            "SELECT celery_task_id, status, attempt, claim_token FROM creator_run_tasks WHERE run_id=$1 ORDER BY id",
            run_id,
        )
        quota = await connection.fetch(
            "SELECT owner_id, status, operation_type FROM workspace_quota_reservation_owners "
            "WHERE owner_id IN (SELECT celery_task_id FROM creator_run_tasks WHERE run_id=$1) ORDER BY owner_id",
            run_id,
        )
        return {
            "run": dict(run) if run else None,
            "tasks": [dict(item) for item in tasks],
            "quota": [dict(item) for item in quota],
        }
    finally:
        await connection.close()


def persist_snapshot(name: str, run_id: int, **fields: object) -> None:
    state = anyio.run(snapshot, run_id)
    (EVIDENCE / name).write_text(json.dumps({**state, **fields}, default=str), encoding="utf-8")


def capture_worker(name: str) -> None:
    logs = docker("logs", name, check=False)
    if logs.returncode == 0:
        (EVIDENCE / f"{name}.worker.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
