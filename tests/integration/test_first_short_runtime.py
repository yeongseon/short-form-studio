"""Opt-in real PostgreSQL/Redis/API/Celery/FFmpeg first-video acceptance test.

Run with FIRST_SHORT_TEST_DATABASE_URL and FIRST_SHORT_TEST_REDIS_URL pointing
only at disposable services. No provider network calls or application mocks.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import asyncpg
import anyio
import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def provision_identity(url: str, schema: str, token: str) -> tuple[int, int]:
    connection = await asyncpg.connect(url, server_settings={"search_path": schema})
    try:
        user_id = await connection.fetchval(
            "INSERT INTO users (auth_subject) VALUES ($1) RETURNING id", uuid4().hex,
        )
        workspace_id = await connection.fetchval(
            "INSERT INTO workspaces (name, slug, owner_id) VALUES ('Runtime test', $1, $2) RETURNING id",
            uuid4().hex, user_id,
        )
        await connection.execute(
            "INSERT INTO workspace_members (workspace_id, user_id) VALUES ($1, $2)",
            workspace_id, user_id,
        )
        await connection.execute(
            "INSERT INTO api_keys (user_id, key_hash, name) VALUES ($1, $2, 'runtime-test')",
            user_id, hashlib.sha256(token.encode()).hexdigest(),
        )
        return int(workspace_id), int(user_id)
    finally:
        await connection.close()


async def count_approvals(url: str, schema: str, run_id: int) -> int:
    connection = await asyncpg.connect(url, server_settings={"search_path": schema})
    try:
        return int(await connection.fetchval(
            "SELECT count(*) FROM creator_stage_reviews WHERE run_id=$1 AND stage_name='TIMELINE_REVIEW'",
            run_id,
        ))
    finally:
        await connection.close()


async def change_schema(url: str, schema: str, drop: bool) -> None:
    connection = await asyncpg.connect(url)
    try:
        statement = f'DROP SCHEMA "{schema}" CASCADE' if drop else f'CREATE SCHEMA "{schema}"'
        await connection.execute(statement)
    finally:
        await connection.close()


def await_api(client: httpx.Client, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        assert process.poll() is None, "API exited during startup; inspect api.log"
        try:
            response = client.get("/healthz")
            if response.status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    pytest.fail("API did not become healthy within 30 seconds")


def wait_for_render(client: httpx.Client, run_id: int) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = client.get(f"/api/creator/runs/{run_id}")
        assert response.status_code == 200, response.text
        run = response.json()
        assert run["status"] != "failed", client.get(f"/api/creator/runs/{run_id}/tasks").text
        if run["current_stage"] == "FINAL_REVIEW":
            return
        time.sleep(0.1)
    pytest.fail("Worker did not produce a reviewed video within 90 seconds")


def test_authenticated_demo_survives_restart_and_renders_downloadable_mp4(tmp_path: Path) -> None:
    database_url = os.getenv("FIRST_SHORT_TEST_DATABASE_URL")
    redis_url = os.getenv("FIRST_SHORT_TEST_REDIS_URL")
    if not database_url or not redis_url:
        pytest.skip("Dedicated PostgreSQL and Redis endpoints are required for real runtime acceptance")
    schema = f"first_short_{uuid4().hex}"
    queue = f"first-short-{uuid4().hex}"
    token = f"runtime-test-{uuid4().hex}"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    separator = "&" if "?" in database_url else "?"
    env = {
        **os.environ,
        "DATABASE_URL": f"{database_url}{separator}search_path={schema}",
        "REDIS_URL": redis_url,
        "ARTIFACT_ROOT": str(artifact_root),
        "STORAGE_BACKEND": "local",
        "ENVIRONMENT": "development",
        "CELERY_TASK_ROUTES": json.dumps({"render_video": {"queue": queue}}),
        "PYTHONPATH": os.pathsep.join(str(ROOT / path) for path in (
            "packages/creator-domain", "packages/creator-service", "packages/creator-provider",
            "apps/api/src", "apps/worker-orchestrator",
        )),
    }
    for name in ("OPENAI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        env.pop(name, None)
    anyio.run(change_schema, database_url, schema, False)
    processes: list[subprocess.Popen[bytes]] = []
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "apps/api",
            env={**env, "DATABASE_URL": database_url, "PGOPTIONS": f"-c search_path={schema}"},
            capture_output=True, check=True, timeout=60,
        )
        workspace, _ = anyio.run(provision_identity, database_url, schema, token)
        foreign_token = f"runtime-test-{uuid4().hex}"
        foreign_workspace, _ = anyio.run(provision_identity, database_url, schema, foreign_token)
        port = free_port()
        with (tmp_path / "api.log").open("wb") as api_log, (tmp_path / "worker.log").open("wb") as worker_log:
            def start_api() -> subprocess.Popen[bytes]:
                process = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "shorts_api.main:app", "--host", "127.0.0.1", "--port", str(port)],
                    cwd=ROOT / "apps/api", env=env, stdout=api_log, stderr=subprocess.STDOUT,
                )
                processes.append(process)
                return process

            api = start_api()
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=20) as client:
                await_api(client, api)
                assert client.get("/api/creator/workspaces").status_code == 401
                client.headers["X-API-Key"] = token
                plan = client.get(f"/api/creator/workspaces/{workspace}/demo-short/plan")
                assert plan.status_code == 200, plan.text
                seed = client.post(f"/api/creator/workspaces/{workspace}/demo-short/runs")
                assert seed.status_code == 201, seed.text
                body = seed.json()
                run_id, project_id = body["run"]["id"], body["seeded_project_id"]
                assert body["run"]["current_stage"] == "TIMELINE_REVIEW"

                api.terminate()
                api.wait(timeout=15)
                api = start_api()
                await_api(client, api)
                timeline = client.get(f"/api/creator/projects/{project_id}/timeline")
                assert timeline.status_code == 200, timeline.text
                timeline_data = timeline.json()
                preview = client.get(f"/api/creator/projects/{project_id}/timeline/preview")
                assert preview.status_code == 200, preview.text
                assert preview.json()["segments"]
                assert preview.json()["timeline_revision"] == timeline_data["revision"]
                media_url = preview.json()["segments"][0]["media_url"]
                media = client.get(media_url)
                assert media.status_code == 200, media.text[:100]
                assert media.content.startswith(b"\x89PNG\r\n\x1a\n")
                stale = client.post(
                    f"/api/creator/runs/{run_id}/approve-timeline-render",
                    json={"expected_revision": timeline_data["revision"] + 1},
                )
                assert stale.status_code == 409, stale.text
                assert anyio.run(count_approvals, database_url, schema, run_id) == 0
                foreign_headers = {"X-API-Key": foreign_token}
                assert client.get(media_url, headers=foreign_headers).status_code == 404
                assert client.get(
                    f"/api/creator/projects/{project_id}/timeline/preview", headers=foreign_headers,
                ).status_code == 404
                assert client.post(
                    f"/api/creator/runs/{run_id}/approve-timeline-render",
                    json={"expected_revision": timeline_data["revision"]}, headers=foreign_headers,
                ).status_code == 404
                assert client.post(
                    f"/api/creator/workspaces/{foreign_workspace}/demo-short/runs",
                ).status_code == 404
                assert client.post(f"/api/creator/runs/{run_id}/render", json={}).status_code == 409
                worker = subprocess.Popen(
                    [sys.executable, "-m", "celery", "-A", "celery_app", "worker", "--pool=solo", "--concurrency=1", "-Q", queue, "--loglevel=INFO"],
                    cwd=ROOT / "apps/worker-orchestrator", env=env, stdout=worker_log, stderr=subprocess.STDOUT,
                )
                processes.append(worker)
                approve = client.post(
                    f"/api/creator/runs/{run_id}/approve-timeline-render",
                    json={"expected_revision": timeline_data["revision"]},
                )
                assert approve.status_code in {200, 202}, approve.text
                wait_for_render(client, run_id)
                startup_log = (tmp_path / "worker.log").read_text()
                assert "raised:" not in startup_log, startup_log
                assert "Traceback (most recent call last)" not in startup_log, startup_log
                records = [json.loads(line) for line in startup_log.splitlines() if line.startswith("{")]
                assert any(record.get("service") == "worker" for record in records), startup_log
                assert anyio.run(count_approvals, database_url, schema, run_id) == 1
                rendered = client.get(f"/api/creator/runs/{run_id}/preview")
                assert rendered.status_code == 200, rendered.text
                artifact_id = rendered.json()["video"]["id"]
                video = client.get(f"/api/creator/runs/{run_id}/artifacts/{artifact_id}/download")
                assert video.status_code == 200, video.text[:200]
                assert client.get(
                    f"/api/creator/runs/{run_id}/artifacts/{artifact_id}/download", headers=foreign_headers,
                ).status_code == 404
                output = tmp_path / "download.mp4"
                output.write_bytes(video.content)
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(output)],
                    check=True, capture_output=True, text=True, timeout=15,
                )
                assert float(json.loads(probe.stdout)["format"]["duration"]) > 0
                published = client.post(
                    f"/api/creator/runs/{run_id}/approve-final", json={},
                )
                assert published.status_code == 200, published.text
                assert client.get(f"/api/creator/runs/{run_id}").json()["current_stage"] == "PUBLISHED"
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        anyio.run(change_schema, database_url, schema, True)
