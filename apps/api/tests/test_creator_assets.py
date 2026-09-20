"""Tests for the workspace-scoped image upload endpoint (SF-03)."""

from __future__ import annotations

import io

import pytest
from PIL import Image
from shorts_api.auth import CurrentUser, require_workspace_access
from shorts_api.main import app


def _png_bytes(width: int = 8, height: int = 12) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def override_workspace_access():
    """Grant access to workspace 1 only; other workspaces 404 (anti-enum)."""

    async def _require_workspace_access(workspace_id: int) -> CurrentUser:
        if workspace_id != 1:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")
        return CurrentUser(user_id=1, workspace_id=workspace_id)

    app.dependency_overrides[require_workspace_access] = _require_workspace_access
    yield
    app.dependency_overrides.pop(require_workspace_access, None)


@pytest.mark.asyncio
async def test_upload_image_returns_created_media_asset(
    client, override_workspace_access
) -> None:
    data = _png_bytes(width=16, height=24)
    response = await client.post(
        "/api/creator/workspaces/1/assets",
        files={"file": ("hero.png", data, "image/png")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workspace_id"] == 1
    assert body["media_type"] == "IMAGE"
    assert body["origin"] == "UPLOADED"
    assert body["mime_type"] == "image/png"
    assert body["width"] == 16
    assert body["height"] == 24
    assert isinstance(body["id"], int)
    assert body["storage_key"].startswith("workspaces/1/assets/")


@pytest.mark.asyncio
async def test_upload_image_rejects_non_image(client, override_workspace_access) -> None:
    response = await client.post(
        "/api/creator/workspaces/1/assets",
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_image_rejects_spoofed_bytes(client, override_workspace_access) -> None:
    response = await client.post(
        "/api/creator/workspaces/1/assets",
        files={"file": ("fake.png", b"not-an-image", "image/png")},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_upload_image_unauthorized_workspace_returns_404(
    client, override_workspace_access
) -> None:
    response = await client.post(
        "/api/creator/workspaces/999/assets",
        files={"file": ("hero.png", _png_bytes(), "image/png")},
    )
    # Anti-enumeration: unauthorized workspace must be 404, never 403.
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_image_requires_api_key() -> None:
    """Without the API key middleware context, creator routes reject with 401."""
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/creator/workspaces/1/assets",
            files={"file": ("hero.png", _png_bytes(), "image/png")},
        )
    assert response.status_code == 401
