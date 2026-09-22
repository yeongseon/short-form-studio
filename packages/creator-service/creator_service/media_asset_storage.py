from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol

import anyio
from creator_domain.models import MediaAsset, MediaOrigin


class _StorageResult(Protocol):
    key: str
    size_bytes: int
    content_type: str
    checksum: str
    storage_provider: str


class MediaStorageBackend(Protocol):
    def upload(
        self, key: str, data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> _StorageResult: ...


@dataclass(frozen=True, slots=True)
class AssetPage:
    items: list[MediaAsset]
    total: int
    limit: int
    offset: int


class MediaAssetStorageBackend(Protocol):
    async def save_asset(self, row: dict[str, object]) -> dict[str, object]: ...

    async def get_asset(self, asset_id: int, workspace_id: int) -> dict[str, object] | None: ...

    async def list_assets(
        self, workspace_id: int, *, media_type: str | None = None,
        project_id: int | None = None, limit: int, offset: int,
    ) -> tuple[list[dict[str, object]], int]: ...


_ORIGIN_SORT_RANK = {
    MediaOrigin.UPLOADED: 0, MediaOrigin.IMPORTED: 1, MediaOrigin.EXTERNAL_URL: 2,
    MediaOrigin.STOCK: 3, MediaOrigin.GENERATED: 4,
}


def _asset_sort_key(row: dict[str, object]) -> tuple[int, float, int]:
    asset = MediaAsset.model_validate(row)
    return (_ORIGIN_SORT_RANK[asset.origin], -asset.created_at.timestamp(), -asset.id)


class InMemoryMediaAssetStorage:
    def __init__(self) -> None:
        self._assets: list[dict[str, object]] = []
        self._next_id = 1
        self._lock = anyio.Lock()

    async def save_asset(self, row: dict[str, object]) -> dict[str, object]:
        async with self._lock:
            saved = MediaAsset.model_validate({**row, "id": self._next_id})
            self._next_id += 1
            self._assets.append(saved.model_dump())
        return saved.model_dump()

    async def get_asset(self, asset_id: int, workspace_id: int) -> dict[str, object] | None:
        for asset in self._assets:
            if asset["id"] == asset_id and asset["workspace_id"] == workspace_id:
                return dict(asset)
        return None

    async def list_assets(
        self, workspace_id: int, *, media_type: str | None = None,
        project_id: int | None = None, limit: int, offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        matched = [
            asset for asset in self._assets
            if asset["workspace_id"] == workspace_id
            and (media_type is None or asset.get("media_type") == media_type)
            and (project_id is None or asset.get("project_id") == project_id)
        ]
        ordered = sorted(matched, key=_asset_sort_key)
        return [dict(asset) for asset in ordered[offset:offset + limit]], len(matched)
