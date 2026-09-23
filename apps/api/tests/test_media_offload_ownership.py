from io import BytesIO
from threading import Event

import anyio
import pytest
from creator_service.media_asset_service import MediaAssetService
from creator_service.media_asset_storage import InMemoryMediaAssetStorage
from creator_service.object_storage import LocalStorageBackend
from PIL import Image


@pytest.mark.asyncio
async def test_cancel_during_upload_finishes_storage_before_return(monkeypatch, tmp_path):
    # Given an upload already executing in a thread.
    backend = LocalStorageBackend(str(tmp_path))
    assets = InMemoryMediaAssetStorage()
    service = MediaAssetService(backend, assets)
    data = BytesIO()
    Image.new("RGB", (2, 2)).save(data, format="PNG")
    entered, release, returned = Event(), Event(), Event()
    scope = anyio.CancelScope()
    original = backend.upload

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    async def upload():
        with scope:
            await service.create_image_asset(workspace_id=1, filename="a.png", data=data.getvalue(), content_type="image/png")
        returned.set()

    original_save = assets.save_asset

    async def checkpoint_save(row):
        await anyio.lowlevel.checkpoint()
        return await original_save(row)

    monkeypatch.setattr(backend, "upload", blocked)
    monkeypatch.setattr(assets, "save_asset", checkpoint_save)
    # When cancellation arrives, upload ownership cannot be abandoned.
    async with anyio.create_task_group() as group:
        group.start_soon(upload)
        try:
            assert await anyio.to_thread.run_sync(entered.wait, 5)
            scope.cancel()
            await anyio.lowlevel.checkpoint()
            assert not returned.is_set()
        finally:
            release.set()
    # Then the completed write has its asset row, even with a real async save checkpoint.
    page = await service.list_assets(workspace_id=1)
    assert page.total == 1
    assert backend.download_bytes(page.items[0].storage_key) == data.getvalue()
