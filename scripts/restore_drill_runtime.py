from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path


TIMEOUT = 120


@dataclass(frozen=True, slots=True)
class DrillError(RuntimeError):
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True, slots=True)
class RuntimeFixture:
    owner_key: str
    foreign_key: str
    revoked_key: str
    workspace_id: int
    project_id: int
    run_id: int
    media_id: int
    artifact_id: int
    port: int = 0


def run(*command: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=TIMEOUT)
    if result.returncode != 0:
        raise DrillError(f"command failed: {' '.join(command)}\n{result.stderr}")
    return result


def docker(*arguments: str) -> subprocess.CompletedProcess[str]:
    return run("docker", *arguments)


def wait_for_postgres(container: str) -> None:
    for _ in range(60):
        if subprocess.run(["docker", "exec", container, "pg_isready", "-U", "restore"], capture_output=True, check=False).returncode == 0:
            return
        time.sleep(1)
    raise DrillError("postgres did not become ready")


def mapped_postgres_url(container: str, password: str) -> str:
    binding = docker("port", container, "5432/tcp").stdout.strip()
    port = binding.rsplit(":", 1)[1]
    return f"postgresql://restore:{password}@127.0.0.1:{port}/restore"


def image_digest(image: str) -> str:
    inspected = docker("image", "inspect", image, "--format={{.Id}}").stdout.strip()
    if not inspected.startswith("sha256:"):
        raise DrillError(f"image lacks immutable digest: {image}")
    return f"{image.split(':', 1)[0]}@{inspected}"


def seed_production_fixture(container: str, media: Path) -> RuntimeFixture:
    owner, foreign, revoked = "owner-restore-key", "foreign-restore-key", "revoked-restore-key"
    hashes = [hashlib.sha256(value.encode()).hexdigest() for value in (owner, foreign, revoked)]
    image_hash = hashlib.sha256((media / "image.png").read_bytes()).hexdigest()
    video_hash = hashlib.sha256((media / "final.mp4").read_bytes()).hexdigest()
    sql = f"""
INSERT INTO users(id,email,name,auth_provider,auth_subject) VALUES (101,'a@example.invalid','A','api_key','restore-a'),(102,'b@example.invalid','B','api_key','restore-b');
INSERT INTO workspaces(id,name,slug,owner_id) VALUES (201,'A','restore-a',101),(202,'B','restore-b',102);
INSERT INTO workspace_members(workspace_id,user_id,role) VALUES (201,101,'owner'),(202,102,'owner');
INSERT INTO api_keys(id,user_id,key_hash,name,revoked_at) VALUES (301,101,'{hashes[0]}','owner',NULL),(302,102,'{hashes[1]}','foreign',NULL),(303,101,'{hashes[2]}','revoked',NOW());
INSERT INTO creator_projects(id,title,source_type,status,workspace_id) VALUES (401,'Restored project','idea','active',201);
INSERT INTO creator_runs(id,project_id,current_stage,status,workspace_id,version,metadata_json) VALUES (501,401,'FINAL_REVIEW','paused',201,1,'{{"render_source":"timeline","render_timeline_revision":1}}');
INSERT INTO creator_timelines(project_id,workspace_id,timeline_id,revision,segments_json) VALUES (401,201,'timeline-restored',1,'[]');
INSERT INTO creator_stage_reviews(run_id,stage_name,review_status,reviewer,notes) VALUES (501,'TIMELINE_REVIEW','approved','101','{{"timeline_id":"timeline-restored","revision":1}}');
INSERT INTO creator_media_assets(id,workspace_id,project_id,run_id,media_type,origin,storage_key,mime_type,metadata) VALUES (601,201,401,501,'IMAGE','UPLOADED','image.png','image/png','{{"sha256":"{image_hash}","storage_provider":"local"}}');
INSERT INTO creator_artifacts(id,run_id,artifact_type,file_path,file_size_bytes,mime_type,storage_key,content_type,size_bytes,workspace_id,project_id,storage_provider,checksum) VALUES (701,501,'video','final.mp4',0,'video/mp4','final.mp4','video/mp4',0,201,401,'local','{video_hash}');
"""
    docker("exec", "-i", container, "psql", "-U", "restore", "-d", "restore", "-c", sql)
    return RuntimeFixture(owner, foreign, revoked, 201, 401, 501, 601, 701)


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def launch_provider_guard(root: Path) -> tuple[subprocess.Popen[bytes], int]:
    port = _free_port()
    marker = root / "provider-invoked"
    program = (
        "from http.server import BaseHTTPRequestHandler,HTTPServer;"
        "from pathlib import Path;"
        f"marker=Path({str(marker)!r});"
        "handler=type('Guard',(BaseHTTPRequestHandler,),{"
        "'do_GET':lambda self:(marker.write_text(self.path),self.send_error(500)),"
        "'do_POST':lambda self:(marker.write_text(self.path),self.send_error(500)),"
        "'log_message':lambda *args:None});"
        f"HTTPServer(('127.0.0.1',{port}),handler).serve_forever()"
    )
    return subprocess.Popen([os.sys.executable, "-c", program]), port


def launch_api(database_url: str, artifact_root: Path, fixture: RuntimeFixture, root: Path, guard_port: int) -> tuple[subprocess.Popen[bytes], RuntimeFixture]:
    port = _free_port()
    env = {
        **os.environ, "DATABASE_URL": database_url, "ARTIFACT_ROOT": str(artifact_root),
        "STORAGE_BACKEND": "local", "ENVIRONMENT": "development", "REDIS_URL": "",
        "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "GOOGLE_API_KEY": "",
        "ELEVENLABS_API_KEY": "", "STABILITY_API_KEY": "",
        "OLLAMA_BASE_URL": f"http://127.0.0.1:{guard_port}",
        "STABLE_DIFFUSION_BASE_URL": f"http://127.0.0.1:{guard_port}",
        "TTS_QWEN3_BASE_URL": f"http://127.0.0.1:{guard_port}",
        "STT_WHISPER_BASE_URL": f"http://127.0.0.1:{guard_port}",
        "TTS_COSYVOICE_BASE_URL": f"http://127.0.0.1:{guard_port}",
    }
    log = (root / "api.log").open("wb")
    process = subprocess.Popen(
        [os.sys.executable, "-m", "uvicorn", "shorts_api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=Path(__file__).parents[1] / "apps/api", env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    return process, replace(fixture, port=port)


def wait_for_api(port: int, process: subprocess.Popen[bytes]) -> None:
    for _ in range(100):
        if process.poll() is not None:
            raise DrillError("real API exited during startup")
        if api_request(port, "/healthz", {})[0] == 200:
            return
        time.sleep(0.1)
    raise DrillError("real API did not become ready")


def api_request(port: int, path: str, headers: dict[str, str]) -> tuple[int, bytes]:
    request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError:
        return 0, b""
