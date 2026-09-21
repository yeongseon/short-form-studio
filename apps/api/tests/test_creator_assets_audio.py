"""Tests for the workspace-scoped audio upload endpoint (SF-05)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from shorts_api.auth import CurrentUser, require_workspace_access
from shorts_api.main import app


def _audio_bytes(seconds: float = 1.0) -> bytes:
    if shutil.which("ffmpeg") is None:  # pragma: no cover - env guard
        pytest.skip("ffmpeg not available")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a.mp3"
        cmd = [
            "ffmpeg", "-y", "-nostdin",
            "-f", "lavfi",
            "-i", f"sine=frequency=440:duration={seconds}",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        if proc.returncode != 0 or not out.exists():  # pragma: no cover - env guard
            pytest.skip("ffmpeg could not produce a test audio file")
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
async def test_upload_audio_returns_created_media_asset(
    client, override_workspace_access
) -> None:
    data = _audio_bytes(seconds=1.0)
    response = await client.post(
        "/api/creator/workspaces/1/assets/audio",
        files={"file": ("voice.mp3", data, "audio/mpeg")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workspace_id"] == 1
    assert body["media_type"] == "AUDIO"
    assert body["origin"] == "UPLOADED"
    assert body["mime_type"] == "audio/mpeg"
    assert body["width"] is None
    assert body["height"] is None
    assert body["duration_seconds"] is not None and body["duration_seconds"] > 0
    assert isinstance(body["id"], int)
    assert body["storage_key"].startswith("workspaces/1/assets/")


@pytest.mark.asyncio
async def test_upload_audio_rejects_non_audio(client, override_workspace_access) -> None:
    response = await client.post(
        "/api/creator/workspaces/1/assets/audio",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_audio_rejects_spoofed_bytes(client, override_workspace_access) -> None:
    response = await client.post(
        "/api/creator/workspaces/1/assets/audio",
        files={"file": ("fake.mp3", b"not-audio", "audio/mpeg")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_audio_unauthorized_workspace_returns_404(
    client, override_workspace_access
) -> None:
    response = await client.post(
        "/api/creator/workspaces/999/assets/audio",
        files={"file": ("voice.mp3", _audio_bytes(), "audio/mpeg")},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_audio_requires_api_key() -> None:
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/creator/workspaces/1/assets/audio",
            files={"file": ("voice.mp3", _audio_bytes(), "audio/mpeg")},
        )
    assert response.status_code == 401
