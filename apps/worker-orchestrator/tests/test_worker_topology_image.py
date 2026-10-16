from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import anyio
import pytest

from tests.worker_topology_runtime import (
    API_KEY,
    API_URL,
    DATABASE_URL,
    EVIDENCE,
    REDIS_URL,
    SCALED_IMAGE_COMMAND,
    Provider,
    capture_worker,
    container_ffmpeg_host_pid,
    docker,
    initialize_database,
    new_run,
    persist_snapshot,
    recover_lost_claim,
    redis_available,
    row,
    send,
    sql,
    stop_run,
    wait_state,
    wait_task,
    wait_redis_queue,
    worker,
)


@pytest.fixture(scope="module", autouse=True)
def runtime() -> Iterator[None]:
    if not DATABASE_URL or not REDIS_URL or not shutil.which("docker"):
        pytest.skip("runtime image environment unavailable")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    initialize_database()
    gateway = docker(
        "network", "inspect", "worker-topology", "-f", "{{(index .IPAM.Config 0).Gateway}}"
    ).stdout.strip()
    server = ThreadingHTTPServer((gateway, 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["TOPOLOGY_PROVIDER_URL"] = f"http://{gateway}:{server.server_port}"
    api_environment = os.environ | {
        "DATABASE_URL": DATABASE_URL,
        "REDIS_URL": REDIS_URL,
        "ENVIRONMENT": "test",
    }
    api = subprocess.Popen(
        [
            "python3",
            "-m",
            "uvicorn",
            "shorts_api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "58064",
        ],
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
            "topology-solo-cancel",
            "topology-scaled-redelivery",
            "topology-scaled-redelivered",
            "topology-scaled-timeout",
            "topology-scaled-ffmpeg",
            "topology-scaled-replacement",
        ):
            capture_worker(name)
            docker("rm", "-f", name, check=False)


def test_shipped_image_runs_production_claims_redelivery_and_fairness() -> None:
    # Given the shipped image using its default production entrypoint and solo command.
    new_run(101)
    new_run(102)
    Provider.calls = 0
    worker("topology-solo-cancel")
    blocked = EVIDENCE / "blocked.json"
    successor = EVIDENCE / "successor.json"
    anyio.run(
        sql,
        """INSERT INTO workspace_quota_reservations(workspace_id, period_start, image_count)
        VALUES(1, date_trunc('month', now()), 1);
        INSERT INTO workspace_quota_reservation_owners(owner_id, workspace_id, period_start, operation_type, status)
        VALUES('blocked-delivery', 1, date_trunc('month', now()), 'image_gen', 'reserved');""",
    )

    # When a long production task owns the worker and successor work is queued.
    send(
        101,
        "blocked-delivery",
        "cooperative",
        blocked,
        provider_url=os.environ["TOPOLOGY_PROVIDER_URL"],
    )
    wait_state(blocked, "provider_done")
    started = time.monotonic()
    send(102, "successor-delivery", "complete", successor)
    time.sleep(1)
    assert not successor.exists()
    stop_run(101)
    cancelled = wait_state(blocked, "cancelled")
    wait_state(successor, "completed")
    delay = time.monotonic() - started

    # Then Postgres owns the claims and cancellation prevents new provider or persistence work.
    first = wait_task("successor-delivery", "success")
    quota = anyio.run(
        row,
        "SELECT status FROM workspace_quota_reservation_owners WHERE owner_id='blocked-delivery'",
    )
    reservation = anyio.run(
        row, "SELECT image_count FROM workspace_quota_reservations WHERE workspace_id=1"
    )
    artifactrows = anyio.run(
        row, "SELECT count(*) AS count FROM creator_artifacts WHERE run_id=101"
    )
    mediarows = anyio.run(
        row, "SELECT count(*) AS count FROM creator_media_assets WHERE run_id=101"
    )
    storage = EVIDENCE / "storage" / "101"
    storage_entries = list(storage.rglob("*")) if storage.exists() else []
    provider_calls = Provider.calls
    assert first["attempt"] == 1
    assert quota is not None and quota["status"] == "cancelled"
    assert reservation is not None and reservation["image_count"] == 0
    assert artifactrows is not None and artifactrows["count"] == 0
    assert mediarows is not None and mediarows["count"] == 0
    assert provider_calls == 1
    assert storage_entries == []
    assert cancelled["second_boundary_suppressed"] is True
    (EVIDENCE / "fairness.json").write_text(
        json.dumps({"successor_delay_seconds": delay}), encoding="utf-8"
    )
    persist_snapshot(
        "cancellation-final-state.json",
        101,
        provider_calls=provider_calls,
        artifactrows=artifactrows["count"],
        media_assetrows=mediarows["count"],
        storage_entries=[str(path) for path in storage_entries],
    )


def test_prefork_hard_timeout_and_ffmpeg_child_die_withworker() -> None:
    # Given the shipped image running the production prefork queue command.
    new_run(103)
    new_run(104)
    new_run(107)
    command = SCALED_IMAGE_COMMAND
    worker("topology-scaled-redelivery", command)
    redelivery_state = EVIDENCE / "active-redelivery.json"
    occupied_state = EVIDENCE / "occupied-slot.json"
    timeout_state = EVIDENCE / "timeout.json"
    ffmpeg_state = EVIDENCE / "ffmpeg.json"

    # When a claimed delivery loses its worker, the broker redelivers it to the exact scaled command.
    send(107, "occupied-slot", "wait", occupied_state, queue="image")
    wait_state(occupied_state, "running")
    send(103, "active-redelivery", "redelivery", redelivery_state, queue="image")
    claimed = wait_state(redelivery_state, "claimed")
    first_claim = wait_task("active-redelivery", "running")
    assert int(claimed["worker_pid"]) > 0
    redelivery_state.with_suffix(".kill").touch()
    broker_redelivery_depth = wait_redis_queue("image")
    anyio.run(recover_lost_claim, "active-redelivery")
    wait_task("active-redelivery", "failed")
    docker("rm", "-f", "topology-scaled-redelivery")
    worker("topology-scaled-redelivered", command)
    wait_state(redelivery_state, "redelivered")
    redelivered = wait_task("active-redelivery", "running")
    assert redelivered["attempt"] == first_claim["attempt"]
    assert redelivered["claim_token"] != first_claim["claim_token"]
    stale_update = anyio.run(
        sql,
        "UPDATE creator_run_tasks SET status='success' WHERE celery_task_id='active-redelivery' AND claim_token=$1",
        (first_claim["claim_token"],),
    )
    assert stale_update == "UPDATE 0"
    stop_run(103)
    wait_state(redelivery_state, "cancelled")
    persist_snapshot(
        "redelivery-final-state.json",
        103,
        broker_redelivery_depth=broker_redelivery_depth,
    )

    new_run(106)
    send(106, "timeout-delivery", "wait", timeout_state, queue="image", time_limit=2)
    wait_state(timeout_state, "running")
    wait_task("timeout-delivery", "failed")
    docker("stop", "topology-redis")
    time.sleep(1)
    assert not redis_available()
    docker("start", "topology-redis")
    deadline = time.monotonic() + 10
    while not redis_available() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert redis_available()
    persist_snapshot("timeout-final-state.json", 106)
    capture_worker("topology-scaled-redelivered")
    docker("rm", "-f", "topology-scaled-redelivered")
    worker("topology-scaled-ffmpeg", command)
    send(104, "ffmpeg-delivery", "ffmpeg_hang", ffmpeg_state, queue="image")
    state = wait_state(ffmpeg_state, "ffmpeg_running")
    host_pid = container_ffmpeg_host_pid("topology-scaled-ffmpeg")
    docker("kill", "--signal=TERM", "topology-scaled-ffmpeg")
    time.sleep(1)
    docker("kill", "--signal=KILL", "topology-scaled-ffmpeg", check=False)
    capture_worker("topology-scaled-ffmpeg")
    anyio.run(sql, "UPDATE creator_runs SET status='cancelled' WHERE id=104")

    # Then forced worker loss removes the real FFmpeg child and a replacement can start.
    assert (
        docker("inspect", "-f", "{{.State.Running}}", "topology-scaled-ffmpeg").stdout.strip()
        == "false"
    )
    assert not Path(f"/proc/{host_pid}").exists()
    worker("topology-scaled-replacement", command)
    new_run(105)
    replacement = EVIDENCE / "replacement.json"
    send(105, "replacement-delivery", "complete", replacement, queue="image")
    wait_state(replacement, "completed")
    (EVIDENCE / "ffmpeg-cleanup.json").write_text(
        json.dumps(
            {"container_pid": state["child_pid"], "host_pid": host_pid, "container_running": False}
        ),
        encoding="utf-8",
    )
