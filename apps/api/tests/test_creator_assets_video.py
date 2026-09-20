"""Tests for the workspace-scoped video upload endpoint (SF-04)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from shorts_api.auth import CurrentUser, require_workspace_access
from shorts_api.main import app


def _video_bytes(seconds: float = 1.0, width: int = 64, height: int = 48) -> bytes:
    if shutil.which("ffmpeg") is None:  # pragma: no cover - env guard
        pytest.skip("ffmpeg not available")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "v.mp4"
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi",
            "-i", f"color=c=blue:s={width}x{height}:d={seconds}",
            "-pix_fmt", "yuv420p",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0 or not out.exists():  # pragma: no cover - env guard
            pytest.skip("ffmpeg could not produce a test video")
        return out.read_bytes()


@pytest.fixture
def override_workspace_access():
    async def _require_workspace_access(workspace_id: int) -> CurrentUser:
        if workspace_id != 1:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")
        return CurrentUser(user_id=1, workspace_id=workspace_id)

    app.dependency_overrides[require_workspace_access] = _require_workspace_access
    yield
    app.dependency_overrides.pop(require_workspace_access, None)


@pytest.mark.asyncio
async def test_upload_video_returns_created_media_asset(
    client, override_workspace_access
) -> None:
    data = _video_bytes(seconds=1.0, width=64, height=48)
    response = await client.post(
        "/api/creator/workspaces/1/assets/videos",
        files={"file": ("clip.mp4", data, "video/mp4")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workspace_id"] == 1
    assert body["media_type"] == "VIDEO"
    assert body["origin"] == "UPLOADED"
    assert body["mime_type"] == "video/mp4"
    assert body["width"] == 64
    assert body["height"] == 48
    assert body["duration_seconds"] is not None and body["duration_seconds"] > 0
    assert isinstance(body["id"], int)
    assert body["storage_key"].startswith("workspaces/1/assets/")


@pytest.mark.asyncio
async def test_upload_video_rejects_non_video(client, override_workspace_access) -> None:
    response = await client.post(
        "/api/creator/workspaces/1/assets/videos",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_video_rejects_spoofed_bytes(client, override_workspace_access) -> None:
    response = await client.post(
        "/api/creator/workspaces/1/assets/videos",
        files={"file": ("fake.mp4", b"not-a-video", "video/mp4")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_video_unauthorized_workspace_returns_404(
    client, override_workspace_access
) -> None:
    response = await client.post(
        "/api/creator/workspaces/999/assets/videos",
        files={"file": ("clip.mp4", _video_bytes(), "video/mp4")},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_video_requires_api_key() -> None:
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/creator/workspaces/1/assets/videos",
            files={"file": ("clip.mp4", _video_bytes(), "video/mp4")},
        )
    assert response.status_code == 401
