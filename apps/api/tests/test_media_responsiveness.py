"""Real async media entry points must rendezvous with a concurrent health request."""

from functools import partial
from io import BytesIO
from threading import Event, get_ident

import anyio
import pytest
from creator_service import media_asset_service as media
from creator_service.media_asset_storage import InMemoryMediaAssetStorage
from creator_service.object_storage import LocalStorageBackend
from httpx import ASGITransport, AsyncClient
from PIL import Image
from shorts_api.main import app


@pytest.mark.asyncio
@pytest.mark.parametrize("seam", ["validate", "dimensions", "upload", "video", "audio", "generated", "backend"])
async def test_health_completes_while_media_operation_is_blocked(monkeypatch, tmp_path, seam):
    # Given a real image/storage pipeline and one controlled synchronous boundary.
    data = BytesIO()
    Image.new("RGB", (3, 2)).save(data, format="PNG")
    service = media.MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    entered, release = Event(), Event()
    loop_thread = get_ident()
    observed = []
    result = []
    target = service._backend()
    attribute = "upload"
    operation = partial(service.create_image_asset, workspace_id=1, filename="a.png", data=data.getvalue(), content_type="image/png")
    if seam in {"validate", "generated"}:
        target, attribute = media, "_validate_image_upload"
    elif seam == "dimensions":
        target, attribute = media, "_probe_image_dimensions"
    elif seam in {"video", "audio"}:
        target, attribute = media, "_probe_media_metadata"
        operation = partial(getattr(service, f"create_{seam}_asset"), workspace_id=1, filename="a", data=b"media", content_type="video/mp4" if seam == "video" else "audio/wav")
    if seam == "generated":
        operation = partial(service.create_generated_image_asset, workspace_id=1, project_id=1, filename="a.png", data=data.getvalue())
    if seam == "backend":
        target, attribute = service, "_backend"
    original = getattr(target, attribute)

    def blocked(*args, **kwargs):
        observed.append(get_ident())
        entered.set()
        assert release.wait(5), "event loop did not release the blocking media operation"
        if seam in {"video", "audio"}:
            return media._ProbedMetadata(3, 2, 1.0)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, attribute, blocked)

    async def upload():
        result.append(await operation())

    # When the operation blocks, health must complete before it is released.
    async with anyio.create_task_group() as group:
        group.start_soon(upload)
        try:
            with anyio.fail_after(6):
                assert await anyio.to_thread.run_sync(entered.wait, 5)
                async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                    assert (await client.get("/healthz")).status_code == 200
                assert not result
                assert observed == [observed[0]] and observed[0] != loop_thread
        finally:
            release.set()
    # Then the same call returns a fully persisted asset after completion.
    assert (await service.get_asset(result[0].id, 1)).storage_key == result[0].storage_key
