"""Validate the merged Compose healthcheck and execute its Node probe locally."""

import os
import shutil
import socket
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Final

import pytest
from pydantic import BaseModel, Field

ROOT: Final = Path(__file__).resolve().parents[3]
VITE_URL: Final = "http://127.0.0.1:5173/"


class Healthcheck(BaseModel):
    test: list[str]
    interval: str
    timeout: str
    retries: int
    start_period: str


class Service(BaseModel):
    healthcheck: Healthcheck


class Services(BaseModel):
    studio_web: Service = Field(alias="studio-web")


class Compose(BaseModel):
    services: Services


@pytest.fixture(scope="module")
def healthcheck() -> Healthcheck:
    # Service env_file resolution is independent of --env-file interpolation.
    with TemporaryDirectory(prefix="dev-healthcheck-") as directory:
        compose_root = Path(directory)
        for name in ("docker-compose.yml", "docker-compose.dev.yml"):
            shutil.copyfile(ROOT / name, compose_root / name)
        shutil.copyfile(ROOT / ".env.example", compose_root / ".env")
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(compose_root / ".env"),
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.dev.yml",
                "config",
                "--format",
                "json",
                "studio-web",
            ],
            cwd=compose_root,
            env={"PATH": os.environ["PATH"], "HOME": directory},
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
    return Compose.model_validate_json(result.stdout).services.studio_web.healthcheck


def test_dev_healthcheck_targets_vite_with_bounded_retries(healthcheck: Healthcheck) -> None:
    # Given the merged dev service, when Docker selects its probe.
    command = healthcheck.test
    # Then it uses the installed Node runtime and the container's Vite port.
    assert command[:3] == ["CMD", "node", "-e"]
    assert VITE_URL in command[3]
    assert healthcheck.interval == "30s"
    assert healthcheck.timeout == "5s"
    assert healthcheck.retries == 3
    assert healthcheck.start_period == "30s"


@pytest.mark.parametrize("status", [200, 503])
def test_dev_healthcheck_exit_tracks_http_status(healthcheck: Healthcheck, status: int) -> None:
    # Given a real local HTTP responder on a per-test ephemeral port.
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(status)
            self.end_headers()

        def log_message(self, format: str, *args: str) -> None:
            return

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # When the configured probe requests that responder.
            probe = healthcheck.test[3].replace(VITE_URL, f"http://127.0.0.1:{server.server_port}/")
            result = subprocess.run(["node", "-e", probe], timeout=6, check=False)
        finally:
            server.shutdown()
            thread.join()

    # Then only a healthy HTTP response succeeds.
    assert result.returncode == (0 if status == 200 else 1)


def test_dev_healthcheck_fails_when_server_is_unavailable(healthcheck: Healthcheck) -> None:
    # Given a reserved but non-listening local port.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        probe = healthcheck.test[3].replace(VITE_URL, f"http://127.0.0.1:{port}/")
        # When the configured probe connects.
        result = subprocess.run(["node", "-e", probe], timeout=6, check=False)
    # Then connection failure is unhealthy.
    assert result.returncode == 1
