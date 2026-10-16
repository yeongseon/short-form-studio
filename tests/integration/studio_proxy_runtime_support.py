from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from uuid import uuid4

import anyio
import asyncpg
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _change_schema(database_url: str, schema: str, drop: bool) -> None:
    connection = await asyncpg.connect(database_url)
    try:
        statement = f'DROP SCHEMA "{schema}" CASCADE' if drop else f'CREATE SCHEMA "{schema}"'
        await connection.execute(statement)
    finally:
        await connection.close()


async def _provision_identity(database_url: str, schema: str, token: str) -> int:
    connection = await asyncpg.connect(database_url, server_settings={"search_path": schema})
    try:
        user_id = await connection.fetchval(
            "INSERT INTO users (auth_subject) VALUES ($1) RETURNING id", uuid4().hex,
        )
        workspace_id = await connection.fetchval(
            "INSERT INTO workspaces (name, slug, owner_id) VALUES ('Proxy runtime', $1, $2) RETURNING id",
            uuid4().hex,
            user_id,
        )
        await connection.execute(
            "INSERT INTO workspace_members (workspace_id, user_id) VALUES ($1, $2)",
            workspace_id,
            user_id,
        )
        await connection.execute(
            "INSERT INTO api_keys (user_id, key_hash, name) VALUES ($1, $2, 'proxy-runtime')",
            user_id,
            hashlib.sha256(token.encode()).hexdigest(),
        )
        return int(workspace_id)
    finally:
        await connection.close()


def _await_health(client: httpx.Client, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        assert process.poll() is None, "runtime process exited during startup"
        try:
            if client.get("/healthz").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.1)
    pytest.fail("runtime did not become healthy within 30 seconds")


@dataclass(frozen=True, slots=True)
class StudioProxyRuntime:
    origin: str
    api_origin: str
    workspace_id: int
    foreign_workspace_id: int
    token: str
    body_temp: Path
    staging_parent: Path


@pytest.fixture(scope="module")
def studio_proxy_runtime(tmp_path_factory: pytest.TempPathFactory) -> Iterator[StudioProxyRuntime]:
    nginx = shutil.which("nginx")
    ffmpeg = shutil.which("ffmpeg")
    database_url = os.getenv("FIRST_SHORT_TEST_DATABASE_URL")
    if nginx is None or ffmpeg is None or database_url is None:
        pytest.skip("nginx, ffmpeg, and a disposable PostgreSQL endpoint are required")

    root = tmp_path_factory.mktemp("studio-proxy-runtime")
    schema = f"studio_proxy_{uuid4().hex}"
    token = f"proxy-runtime-{uuid4().hex}"
    foreign_token = f"proxy-foreign-{uuid4().hex}"
    artifact_root = root / "artifacts"
    body_temp = root / "body"
    artifact_root.mkdir()
    body_temp.mkdir()
    studio_dist = ROOT / "apps/studio-web/dist"
    if not (studio_dist / "index.html").is_file():
        pytest.skip("the built Studio is required")
    env = {
        **os.environ,
        "DATABASE_URL": f"{database_url}{'&' if '?' in database_url else '?'}search_path={schema}",
        "ARTIFACT_ROOT": str(artifact_root),
        "STORAGE_BACKEND": "local",
        "ENVIRONMENT": "development",
        "TMPDIR": str(root),
        "PYTHONPATH": os.pathsep.join(str(ROOT / path) for path in (
            "packages/creator-domain", "packages/creator-service", "packages/creator-provider", "apps/api/src",
        )),
    }
    anyio.run(_change_schema, database_url, schema, False)
    processes: list[subprocess.Popen[bytes]] = []
    api_log = (root / "api.log").open("wb")
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=ROOT / "apps/api",
            env={**env, "DATABASE_URL": database_url, "PGOPTIONS": f"-c search_path={schema}"},
            check=True,
            capture_output=True,
            timeout=60,
        )
        workspace_id = anyio.run(_provision_identity, database_url, schema, token)
        foreign_workspace_id = anyio.run(_provision_identity, database_url, schema, foreign_token)
        api_port = _free_port()
        api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "shorts_api.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
            cwd=ROOT / "apps/api",
            env=env,
            stdout=api_log,
            stderr=subprocess.STDOUT,
        )
        processes.append(api)
        api_origin = f"http://127.0.0.1:{api_port}"
        with httpx.Client(base_url=api_origin, timeout=5) as client:
            _await_health(client, api)

        nginx_port = _free_port()
        template = (ROOT / "apps/studio-web/nginx.conf.template").read_text()
        configured = template.replace("${API_KEY}", token)
        configured = configured.replace("listen 8080;", f"listen 127.0.0.1:{nginx_port};")
        configured = configured.replace("http://api:8000", api_origin)
        configured = configured.replace("/usr/share/nginx/html", str(studio_dist))
        config = root / "nginx.conf"
        config.write_text(
            f"pid {root}/nginx.pid; error_log {root}/nginx-error.log;\n"
            f"events {{}}\nhttp {{ include /etc/nginx/mime.types; access_log off; "
            f"client_body_temp_path {body_temp}; "
            f"proxy_temp_path {root}/proxy;\n{configured}\n}}\n",
        )
        nginx_process = subprocess.Popen(
            [nginx, "-p", str(root), "-c", str(config), "-g", "daemon off;"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        processes.append(nginx_process)
        origin = f"http://127.0.0.1:{nginx_port}"
        with httpx.Client(base_url=origin, timeout=5) as client:
            _await_health(client, nginx_process)
        yield StudioProxyRuntime(
            origin, api_origin, workspace_id, foreign_workspace_id, token, body_temp, root,
        )
    finally:
        for process in reversed(processes):
            process.terminate()
            process.wait(timeout=15)
        api_log.close()
        anyio.run(_change_schema, database_url, schema, True)
