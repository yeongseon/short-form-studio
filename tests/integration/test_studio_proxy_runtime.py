"""Exercise the shipped nginx template without exposing a key to browser code."""

from pathlib import Path
from dataclasses import dataclass
import shutil
import socket
import subprocess
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class UploadBoundary:
    route: str
    api_limit: int
    nginx_limit: int


UPLOAD_BOUNDARIES = (
    UploadBoundary("/api/creator/workspaces/1/assets", 25 * 1024 * 1024, 26 * 1024 * 1024),
    UploadBoundary("/api/creator/workspaces/1/assets/audio", 100 * 1024 * 1024, 101 * 1024 * 1024),
    UploadBoundary("/api/creator/workspaces/1/assets/videos", 500 * 1024 * 1024, 501 * 1024 * 1024),
)


def test_nginx_injects_runtime_key_and_blocks_cross_origin_mutation(tmp_path: Path) -> None:
    nginx = shutil.which("nginx")
    if nginx is None:
        pytest.skip("nginx executable is required for the actual proxy check")
    expected_key = "synthetic-proxy-test-only"

    class AuthenticatedUpstream(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            authenticated = self.headers.get("X-API-Key") == expected_key
            self.send_response(200 if authenticated else 401)
            self.end_headers()
            self.wfile.write(b"authenticated" if authenticated else b"missing key")

        def do_POST(self) -> None:
            self.do_GET()

        def log_message(self, format: str, *args: str) -> None:
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), AuthenticatedUpstream)
    thread = Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    template = (ROOT / "apps/studio-web/nginx.conf.template").read_text()
    configured = template.replace("${API_KEY}", expected_key)
    configured = configured.replace("listen 8080;", f"listen 127.0.0.1:{port};")
    configured = configured.replace("http://api:8000", f"http://127.0.0.1:{upstream.server_port}")
    configured = configured.replace("/usr/share/nginx/html", str(tmp_path))
    config = tmp_path / "nginx.conf"
    config.write_text(
        f"pid {tmp_path}/nginx.pid; error_log {tmp_path}/error.log;\n"
        f"events {{}}\nhttp {{ access_log off; client_body_temp_path {tmp_path}/body; "
        f"proxy_temp_path {tmp_path}/proxy;\n{configured}\n}}\n",
    )
    (tmp_path / "index.html").write_text("<html>Studio test</html>")
    process = subprocess.Popen([nginx, "-p", str(tmp_path), "-c", str(config), "-g", "daemon off;"])
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
            for _ in range(50):
                assert process.poll() is None, (tmp_path / "error.log").read_text()
                try:
                    response = client.get("/api/creator/workspaces")
                    break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                pytest.fail("nginx did not start")
            assert response.status_code == 200
            assert response.text == "authenticated"
            assert expected_key not in client.get("/").text
            assert client.post("/api/creator/demo").status_code == 403
            assert client.post("/api/creator/demo", headers={"Origin": "https://foreign.invalid"}).status_code == 403
            allowed = client.post("/api/creator/demo", headers={"Origin": f"http://127.0.0.1:{port}"})
            assert allowed.status_code == 200
    finally:
        process.terminate()
        process.wait(timeout=10)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("boundary", UPLOAD_BOUNDARIES)
def test_nginx_enforces_upload_specific_multipart_boundary(
    tmp_path: Path,
    boundary: UploadBoundary,
) -> None:
    nginx = shutil.which("nginx")
    if nginx is None:
        pytest.skip("nginx executable is required for the upload boundary check")
    expected_key = "synthetic-upload-test-only"

    class UploadUpstream(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            authenticated = self.headers.get("X-API-Key") == expected_key
            content_length = int(self.headers.get("Content-Length", "0"))
            file_size = int(self.headers.get("X-Test-File-Size", "0"))
            remaining = content_length
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 1024 * 1024))
                if not chunk:
                    break
                remaining -= len(chunk)
            within_api_limit = file_size <= boundary.api_limit
            self.send_response(201 if authenticated and within_api_limit else 400)
            self.end_headers()

        def log_message(self, format: str, *args: str) -> None:
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UploadUpstream)
    thread = Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    template = (ROOT / "apps/studio-web/nginx.conf.template").read_text()
    configured = template.replace("${API_KEY}", expected_key)
    configured = configured.replace("listen 8080;", f"listen 127.0.0.1:{port};")
    configured = configured.replace("http://api:8000", f"http://127.0.0.1:{upstream.server_port}")
    configured = configured.replace("/usr/share/nginx/html", str(tmp_path))
    config = tmp_path / "nginx.conf"
    config.write_text(
        f"pid {tmp_path}/nginx.pid; error_log {tmp_path}/error.log;\n"
        f"events {{}}\nhttp {{ access_log off; client_body_temp_path {tmp_path}/body; "
        f"proxy_temp_path {tmp_path}/proxy;\n{configured}\n}}\n",
    )
    (tmp_path / "index.html").write_text("<html>Studio test</html>")
    process = subprocess.Popen([nginx, "-p", str(tmp_path), "-c", str(config), "-g", "daemon off;"])
    try:
        origin = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=origin, timeout=120) as client:
            for _ in range(50):
                assert process.poll() is None, (tmp_path / "error.log").read_text()
                try:
                    client.get("/healthz")
                    break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                pytest.fail("nginx did not start")

            for size in (1024, 2 * 1024 * 1024, boundary.api_limit - 4096):
                upload = tmp_path / f"under-{size}.bin"
                upload.touch()
                upload.truncate(size)
                with upload.open("rb") as body:
                    response = client.post(
                        boundary.route,
                        headers={"Origin": origin, "X-Test-File-Size": str(size)},
                        files={"file": (upload.name, body, "application/octet-stream")},
                    )
                assert response.status_code == 201

            api_oversized = tmp_path / "api-over.bin"
            api_oversized.touch()
            api_oversized.truncate(boundary.api_limit + 1)
            with api_oversized.open("rb") as body:
                response = client.post(
                    boundary.route,
                    headers={"Origin": origin, "X-Test-File-Size": str(boundary.api_limit + 1)},
                    files={"file": (api_oversized.name, body, "application/octet-stream")},
                )
            assert response.status_code == 400

            multipart_oversized = tmp_path / "multipart-over.bin"
            multipart_oversized.touch()
            multipart_oversized.truncate(boundary.nginx_limit + 1)
            with multipart_oversized.open("rb") as body:
                response = client.post(
                    boundary.route,
                    headers={"Origin": origin, "X-Test-File-Size": str(boundary.nginx_limit + 1)},
                    files={"file": (multipart_oversized.name, body, "application/octet-stream")},
                )
            assert response.status_code == 413
            assert response.headers["content-type"].startswith("text/html")
    finally:
        process.terminate()
        process.wait(timeout=10)
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)
