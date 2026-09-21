from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from creator_service.media_asset_service import (
    AssetPage,
    InMemoryMediaAssetStorage,
    MediaAssetService,
)


def _ts(offset: int = 0) -> datetime:
    return datetime(2026, 1, 1, 0, 0, offset, tzinfo=timezone.utc)


def _row(
    *,
    workspace_id: int,
    media_type: MediaType,
    origin: MediaOrigin,
    project_id: int | None = None,
    created_offset: int = 0,
    storage_key: str | None = "k",
) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "run_id": None,
        "media_type": media_type.value,
        "origin": origin.value,
        "storage_key": storage_key,
        "mime_type": None,
        "width": None,
        "height": None,
        "duration_seconds": None,
        "source_url": None,
        "metadata": {},
        "created_at": _ts(created_offset),
    }


async def _seed(storage: InMemoryMediaAssetStorage, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        await storage.save_asset(row)


@pytest.mark.asyncio
async def test_list_assets_returns_only_own_workspace() -> None:
    storage = InMemoryMediaAssetStorage()
    await _seed(
        storage,
        [
            _row(workspace_id=1, media_type=MediaType.IMAGE, origin=MediaOrigin.UPLOADED),
            _row(workspace_id=2, media_type=MediaType.IMAGE, origin=MediaOrigin.UPLOADED),
        ],
    )
    service = MediaAssetService(asset_storage=storage)

    page = await service.list_assets(workspace_id=1)

    assert isinstance(page, AssetPage)
    assert all(isinstance(a, MediaAsset) for a in page.items)
    assert [a.workspace_id for a in page.items] == [1]
    assert page.total == 1


@pytest.mark.asyncio
async def test_list_assets_filters_by_media_type() -> None:
    storage = InMemoryMediaAssetStorage()
    await _seed(
        storage,
        [
            _row(workspace_id=1, media_type=MediaType.IMAGE, origin=MediaOrigin.UPLOADED),
            _row(workspace_id=1, media_type=MediaType.VIDEO, origin=MediaOrigin.UPLOADED),
            _row(workspace_id=1, media_type=MediaType.AUDIO, origin=MediaOrigin.UPLOADED),
        ],
    )
    service = MediaAssetService(asset_storage=storage)

    page = await service.list_assets(workspace_id=1, media_type=MediaType.VIDEO)

    assert [a.media_type for a in page.items] == [MediaType.VIDEO]
    assert page.total == 1


@pytest.mark.asyncio
async def test_list_assets_filters_by_project() -> None:
    storage = InMemoryMediaAssetStorage()
    await _seed(
        storage,
        [
            _row(workspace_id=1, media_type=MediaType.IMAGE, origin=MediaOrigin.UPLOADED, project_id=5),
            _row(workspace_id=1, media_type=MediaType.IMAGE, origin=MediaOrigin.UPLOADED, project_id=9),
        ],
    )
    service = MediaAssetService(asset_storage=storage)

    page = await service.list_assets(workspace_id=1, project_id=5)

    assert [a.project_id for a in page.items] == [5]
    assert page.total == 1


@pytest.mark.asyncio
async def test_list_assets_orders_uploaded_before_generated_then_newest() -> None:
    storage = InMemoryMediaAssetStorage()
    await _seed(
        storage,
        [
            _row(workspace_id=1, media_type=MediaType.IMAGE, origin=MediaOrigin.GENERATED, created_offset=1),
            _row(workspace_id=1, media_type=MediaType.IMAGE, origin=MediaOrigin.UPLOADED, created_offset=2),
            _row(workspace_id=1, media_type=MediaType.IMAGE, origin=MediaOrigin.UPLOADED, created_offset=5),
        ],
    )
    service = MediaAssetService(asset_storage=storage)

    page = await service.list_assets(workspace_id=1)

    origins = [a.origin for a in page.items]
    # Uploaded first (newest uploaded before older uploaded), then generated.
    assert origins == [MediaOrigin.UPLOADED, MediaOrigin.UPLOADED, MediaOrigin.GENERATED]
    assert page.items[0].id != page.items[1].id
    # newest uploaded (offset 5) before older uploaded (offset 2)
    assert page.items[0].created_at > page.items[1].created_at


@pytest.mark.asyncio
async def test_list_assets_pagination_is_stable() -> None:
    storage = InMemoryMediaAssetStorage()
    await _seed(
        storage,
        [
            _row(
                workspace_id=1,
                media_type=MediaType.IMAGE,
                origin=MediaOrigin.UPLOADED,
                created_offset=i,
            )
            for i in range(5)
        ],
    )
    service = MediaAssetService(asset_storage=storage)

    first = await service.list_assets(workspace_id=1, limit=2, offset=0)
    second = await service.list_assets(workspace_id=1, limit=2, offset=2)
    third = await service.list_assets(workspace_id=1, limit=2, offset=4)

    assert first.total == 5 and second.total == 5 and third.total == 5
    assert len(first.items) == 2 and len(second.items) == 2 and len(third.items) == 1
    ids = [a.id for a in (*first.items, *second.items, *third.items)]
    assert len(set(ids)) == 5  # no overlaps across pages


@pytest.mark.asyncio
async def test_list_assets_rejects_invalid_pagination() -> None:
    service = MediaAssetService(asset_storage=InMemoryMediaAssetStorage())
    with pytest.raises(ValueError):
        await service.list_assets(workspace_id=1, limit=0)
    with pytest.raises(ValueError):
        await service.list_assets(workspace_id=1, offset=-1)


@pytest.mark.asyncio
async def test_list_assets_empty_workspace_returns_empty_page() -> None:
    service = MediaAssetService(asset_storage=InMemoryMediaAssetStorage())
    page = await service.list_assets(workspace_id=42)
    assert page.items == []
    assert page.total == 0
