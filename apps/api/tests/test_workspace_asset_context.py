import io
from pathlib import Path

from creator_service.media_asset_service import InMemoryMediaAssetStorage, MediaAssetService
from creator_service.object_storage import LocalStorageBackend
from fastapi import HTTPException
from httpx import AsyncClient
from PIL import Image
import pytest

from shorts_api.auth import CurrentUser, require_workspace_access
from shorts_api.main import app
from shorts_api.routes import creator_assets


@pytest.mark.asyncio
async def test_workspace_asset_operations_use_authorized_path_not_default_context(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    image = io.BytesIO()
    Image.new("RGB", (8, 12), (30, 60, 90)).save(image, format="PNG")
    service = MediaAssetService(
        storage_backend=LocalStorageBackend(str(tmp_path)), asset_storage=InMemoryMediaAssetStorage(),
    )
    monkeypatch.setattr(creator_assets, "media_asset_service", service)

    async def access(workspace_id: int) -> CurrentUser:
        if workspace_id not in {1, 2}:
            raise HTTPException(404, "Not found")
        return CurrentUser(user_id=1, workspace_id=1)

    app.dependency_overrides[require_workspace_access] = access
    try:
        uploaded = await client.post(
            "/api/creator/workspaces/2/assets",
            files={"file": ("example.png", image.getvalue(), "image/png")},
        )
        assert uploaded.status_code == 201, uploaded.text
        asset = uploaded.json()
        assert asset["workspace_id"] == 2
        assert asset["storage_key"].startswith("workspaces/2/assets/")
        listing = await client.get("/api/creator/workspaces/2/assets")
        assert listing.json()["total"] == 1
        assert listing.json()["items"][0]["id"] == asset["id"]
        assert (await client.get("/api/creator/workspaces/1/assets")).json()["total"] == 0
        assert (await client.get(f"/api/creator/workspaces/2/assets/{asset['id']}")).status_code == 200
        assert (await client.get(f"/api/creator/workspaces/1/assets/{asset['id']}")).status_code == 404
        assert (await client.get("/api/creator/workspaces/999/assets")).status_code == 404
    finally:
        app.dependency_overrides.pop(require_workspace_access, None)
