"""Exercise the shipped nginx template without exposing a key to browser code."""

from pathlib import Path
import shutil
import socket
import subprocess
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]


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
