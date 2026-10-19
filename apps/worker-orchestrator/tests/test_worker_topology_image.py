from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from decimal import Decimal
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
    send_scene_image,
    send_delayed_failure,
    sql,
    stop_run,
    wait_state,
    wait_task,
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
            "topology-scaled-timeout",
            "topology-scaled-ffmpeg",
            "topology-scaled-replacement",
        ):
            capture_worker(name)
            docker("rm", "-f", name, check=False)


def test_shipped_image_runs_production_claims_redelivery_and_fairness() -> None:
    # Given the shipped image using its default production entrypoint and solo command.
    new_run(100)
    new_run(101)
    new_run(102)
    Provider.calls = 0
    worker("topology-solo-cancel")
    boundaries = EVIDENCE / "boundaries.json"
    blocked = EVIDENCE / "blocked.json"
    successor = EVIDENCE / "successor.json"
    anyio.run(
        sql,
        """INSERT INTO workspace_quota_reservations(workspace_id, period_start, image_count)
        VALUES(1, date_trunc('month', now()), 1);
        INSERT INTO workspace_quota_reservation_owners(owner_id, workspace_id, period_start, operation_type, status)
        VALUES('blocked-delivery', 1, date_trunc('month', now()), 'image_gen', 'reserved');""",
    )

    # When the uncancelled branch crosses both provider and artifact persistence boundaries.
    send(
        100,
        "boundary-delivery",
        "cancellation_gate",
        boundaries,
        provider_url=os.environ["TOPOLOGY_PROVIDER_URL"],
    )
    wait_state(boundaries, "provider_done")
    boundaries.with_suffix(".continue").touch()
    wait_state(boundaries, "boundaries_completed")
    boundary_artifacts = anyio.run(
        row, "SELECT count(*) AS count FROM creator_artifacts WHERE run_id=100"
    )
    assert Provider.calls == 2
    assert boundary_artifacts is not None and boundary_artifacts["count"] == 1
    assert (EVIDENCE / "storage" / "100" / "artifact.bin").is_file()
    Provider.calls = 0

    # When a long production task owns the worker and successor work is queued.
    send(
        101,
        "blocked-delivery",
        "cancellation_gate",
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
    capture_worker("topology-solo-cancel")
    docker("rm", "-f", "topology-solo-cancel")


def test_prefork_hard_timeout_and_ffmpeg_child_die_withworker() -> None:
    # Given the shipped image running the production prefork queue command.
    new_run(103)
    new_run(104)
    new_run(107)
    new_run(108)
    command = SCALED_IMAGE_COMMAND
    worker("topology-scaled-redelivery", command)
    redelivery_state = EVIDENCE / "active-redelivery.json"
    occupied_state = EVIDENCE / "occupied-slot.json"
    ffmpeg_state = EVIDENCE / "ffmpeg.json"

    # When a claimed delivery loses its worker, the broker redelivers it to the exact scaled command.
    send(107, "occupied-slot", "wait", occupied_state, queue="image")
    wait_state(occupied_state, "running")
    send(103, "active-redelivery", "redelivery", redelivery_state, queue="image")
    claimed = wait_state(redelivery_state, "claimed")
    first_claim = wait_task("active-redelivery", "running")
    assert int(claimed["worker_pid"]) > 0
    anyio.run(recover_lost_claim, "active-redelivery")
    wait_task("active-redelivery", "failed")
    redelivery_state.with_suffix(".kill").touch()
    wait_state(redelivery_state, "redelivered")
    redelivered = wait_task("active-redelivery", "running")
    assert redelivered["attempt"] == first_claim["attempt"]
    assert redelivered["claim_token"] != first_claim["claim_token"]
    anyio.run(
        sql,
        """INSERT INTO workspace_quota_reservations(workspace_id, period_start, image_count)
        VALUES(1, date_trunc('month', now()), 1)
        ON CONFLICT (workspace_id, period_start) DO UPDATE
        SET image_count = workspace_quota_reservations.image_count + 1;
        INSERT INTO workspace_quota_reservation_owners
        (owner_id, workspace_id, period_start, operation_type, status)
        VALUES('active-redelivery', 1, date_trunc('month', now()), 'image_gen', 'reserved');""",
    )
    send_delayed_failure("active-redelivery", str(first_claim["claim_token"]))
    successor = wait_task("active-redelivery", "running")
    successor_run = anyio.run(row, "SELECT status FROM creator_runs WHERE id=103")
    successor_quota = anyio.run(
        row,
        "SELECT status FROM workspace_quota_reservation_owners WHERE owner_id='active-redelivery'",
    )
    assert successor["claim_token"] == redelivered["claim_token"]
    assert successor_run is not None and successor_run["status"] == "running"
    assert successor_quota is not None and successor_quota["status"] == "reserved"
    persist_snapshot("redelivery-final-state.json", 103)
    capture_worker("topology-scaled-redelivery")
    docker("rm", "-f", "topology-scaled-redelivery")
    worker("topology-scaled-redelivered", command)

    broker_loss_state = EVIDENCE / "active-broker-loss.json"
    send(108, "broker-loss-delivery", "wait", broker_loss_state, queue="image")
    wait_state(broker_loss_state, "running")
    docker("stop", "topology-redis")
    time.sleep(1)
    assert not redis_available()
    docker("start", "topology-redis")
    deadline = time.monotonic() + 10
    while not redis_available() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert redis_available()
    capture_worker("topology-scaled-redelivered")
    docker("rm", "-f", "topology-scaled-redelivered")
    docker("exec", "topology-redis", "redis-cli", "DEL", "image")
    worker(
        "topology-scaled-timeout",
        command,
        {
            "WORKER_TOPOLOGY_ALLOW_PRODUCTION_TIMEOUT_OVERRIDE": "1",
            "WORKER_TOPOLOGY_PRODUCTION_HARD_TIME_LIMIT": "2",
        },
    )

    new_run(106)
    anyio.run(
        sql,
        """UPDATE creator_runs
        SET current_stage='VISUAL_ASSET_GENERATING' WHERE id=106;
        INSERT INTO creator_visual_plans(run_id, scenes_json, version)
        VALUES(106, '[{"scene_id":"scene-persisted","section_id":"section-1","scene_index":0,
        "section_type":"body","original_text":"persisted provider",
        "prompt":"persisted provider"},
        {"scene_id":"scene-timeout","section_id":"section-1","scene_index":1,
        "section_type":"body","original_text":"blocking provider",
        "prompt":"blocking provider"}]', 1);
        INSERT INTO workspace_quota_reservations(
          workspace_id, period_start, image_count, reserved_estimated_cost_usd)
        VALUES(1, date_trunc('month', now()), 2, 0.08)
        ON CONFLICT (workspace_id, period_start) DO UPDATE
        SET image_count = workspace_quota_reservations.image_count + 2,
            reserved_estimated_cost_usd =
              workspace_quota_reservations.reserved_estimated_cost_usd + 0.08;
        INSERT INTO workspace_quota_reservation_owners
        (owner_id, workspace_id, period_start, operation_type, status, estimated_cost_usd)
        VALUES('timeout-delivery', 1, date_trunc('month', now()), 'image_gen', 'reserved', 0.08);""",
    )
    Provider.image_calls = 0
    Provider.image_successes_before_block = 1
    Provider.image_release.clear()
    send_scene_image(106, "timeout-delivery", time_limit=2)
    deadline = time.monotonic() + 15
    while Provider.image_calls == 0 and time.monotonic() < deadline:
        time.sleep(0.1)
    assert Provider.image_calls == 2
    wait_task("timeout-delivery", "failed")
    Provider.image_release.set()
    timeout_run = anyio.run(row, "SELECT status FROM creator_runs WHERE id=106")
    timeout_quota = anyio.run(
        row,
        "SELECT status, estimated_cost_usd FROM workspace_quota_reservation_owners "
        "WHERE owner_id='timeout-delivery'",
    )
    timeout_attempt = anyio.run(
        row,
        "SELECT status FROM workspace_quota_reservation_attempts "
        "WHERE owner_id='timeout-delivery'",
    )
    timeout_assets = anyio.run(
        row,
        "SELECT asset_path FROM creator_visual_assets WHERE run_id=106 AND scene_id='scene-persisted'",
    )
    timeout_files = list((EVIDENCE / "storage" / "106" / "scenes").glob("*.png"))
    assert timeout_run is not None and timeout_run["status"] == "failed"
    assert timeout_quota is not None and timeout_quota["status"] == "billable_unknown"
    assert timeout_quota["estimated_cost_usd"] == Decimal("0.080000")
    assert timeout_attempt is not None and timeout_attempt["status"] == "unknown"
    assert timeout_assets is not None
    assert Path(timeout_assets["asset_path"]).is_file()
    assert timeout_files == [Path(timeout_assets["asset_path"])]
    replacement = EVIDENCE / "timeout-replacement.json"
    new_run(109)
    send(109, "timeout-replacement", "complete", replacement, queue="image")
    wait_state(replacement, "completed")
    persist_snapshot("timeout-final-state.json", 106)
    capture_worker("topology-scaled-timeout")
    docker("rm", "-f", "topology-scaled-timeout")
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
