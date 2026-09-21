"""Tests for the workspace-scoped asset library GET endpoints (SF-07)."""

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


@pytest.fixture(autouse=True)
def _isolate_asset_storage():
    """Reset the shared media_asset_service in-memory storage per test.

    The route uses a module-level singleton whose InMemoryMediaAssetStorage
    otherwise accumulates assets across tests, polluting list/filter assertions.
    """
    from creator_service.media_asset_service import (
        InMemoryMediaAssetStorage,
        media_asset_service,
    )

    media_asset_service._asset_storage = InMemoryMediaAssetStorage()
    yield


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


async def _upload_image(client, filename: str = "a.png") -> int:
    response = await client.post(
        "/api/creator/workspaces/1/assets",
        files={"file": (filename, _png_bytes(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.asyncio
async def test_list_assets_returns_uploaded_asset(client, override_workspace_access) -> None:
    asset_id = await _upload_image(client, "hero.png")

    response = await client.get("/api/creator/workspaces/1/assets")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 1
    assert any(item["id"] == asset_id for item in body["items"])
    listed = next(item for item in body["items"] if item["id"] == asset_id)
    assert listed["workspace_id"] == 1
    assert listed["media_type"] == "IMAGE"
    assert listed["origin"] == "UPLOADED"


@pytest.mark.asyncio
async def test_list_assets_filters_by_media_type(client, override_workspace_access) -> None:
    await _upload_image(client, "img.png")

    response = await client.get("/api/creator/workspaces/1/assets?media_type=VIDEO")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_assets_pagination(client, override_workspace_access) -> None:
    for i in range(3):
        await _upload_image(client, f"a{i}.png")

    response = await client.get("/api/creator/workspaces/1/assets?limit=2&offset=0")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] >= 3
    assert body["limit"] == 2
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_list_assets_rejects_invalid_pagination(client, override_workspace_access) -> None:
    response = await client.get("/api/creator/workspaces/1/assets?limit=0")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_assets_unauthorized_workspace_returns_404(
    client, override_workspace_access
) -> None:
    response = await client.get("/api/creator/workspaces/999/assets")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_asset_detail_returns_asset(client, override_workspace_access) -> None:
    asset_id = await _upload_image(client, "d.png")

    response = await client.get(f"/api/creator/workspaces/1/assets/{asset_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == asset_id
    assert body["workspace_id"] == 1


@pytest.mark.asyncio
async def test_get_asset_detail_missing_returns_404(client, override_workspace_access) -> None:
    response = await client.get("/api/creator/workspaces/1/assets/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_asset_detail_unauthorized_workspace_returns_404(
    client, override_workspace_access
) -> None:
    response = await client.get("/api/creator/workspaces/999/assets/1")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_assets_requires_api_key() -> None:
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/creator/workspaces/1/assets")
    assert response.status_code == 401
