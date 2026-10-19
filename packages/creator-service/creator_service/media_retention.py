from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import os
from functools import partial
from typing import Protocol

from .blocking_io import BlockingIO


@dataclass(frozen=True, slots=True)
class MediaRetentionPolicy:
    original_days: int = 0
    intermediate_days: int = 0
    final_video_days: int = 0
    grace_days: int = 7
    enabled: bool = False
    dry_run: bool = True

    @classmethod
    def from_env(cls) -> MediaRetentionPolicy:
        return cls(
            original_days=int(os.getenv("MEDIA_RETENTION_ORIGINAL_DAYS", "0")),
            intermediate_days=int(os.getenv("MEDIA_RETENTION_INTERMEDIATE_DAYS", "0")),
            final_video_days=int(os.getenv("MEDIA_RETENTION_FINAL_VIDEO_DAYS", "0")),
            grace_days=int(os.getenv("MEDIA_RETENTION_GRACE_DAYS", "7")),
            enabled=os.getenv("MEDIA_RETENTION_ENABLED", "false").lower() == "true",
            dry_run=os.getenv("MEDIA_RETENTION_DRY_RUN", "true").lower() != "false",
        )


@dataclass(frozen=True, slots=True)
class RetentionAsset:
    id: int
    workspace_id: int
    storage_key: str
    origin: str
    media_type: str
    created_at: datetime


def _retention_days(asset: RetentionAsset, policy: MediaRetentionPolicy) -> int:
    if asset.origin != "GENERATED":
        return policy.original_days
    if asset.media_type == "VIDEO":
        return policy.final_video_days
    return policy.intermediate_days


def select_retention_candidates(
    assets: list[RetentionAsset], *, policy: MediaRetentionPolicy,
    referenced_asset_ids: frozenset[int], approved_asset_ids: frozenset[int],
    workspace_id: int, now: datetime,
) -> list[RetentionAsset]:
    selected: list[RetentionAsset] = []
    for asset in assets:
        days = _retention_days(asset, policy)
        protected = asset.id in referenced_asset_ids or asset.id in approved_asset_ids
        owned = asset.workspace_id == workspace_id and asset.storage_key.startswith(
            f"workspaces/{workspace_id}/assets/"
        )
        expired = days > 0 and asset.created_at <= now - timedelta(days=days + policy.grace_days)
        if owned and expired and not protected:
            selected.append(asset)
    return selected


class RetentionStorage(Protocol):
    async def list_retention_assets(self, workspace_id: int, limit: int) -> list[RetentionAsset]: ...
    async def referenced_asset_ids(self, workspace_id: int) -> frozenset[int]: ...
    async def approved_asset_ids(self, workspace_id: int) -> frozenset[int]: ...
    async def claim_retained_asset(self, asset_id: int, workspace_id: int) -> bool: ...
    async def release_retained_asset(self, asset_id: int, workspace_id: int) -> None: ...
    async def delete_retained_asset(self, asset_id: int, workspace_id: int) -> None: ...


class DeletableObjects(Protocol):
    def delete(self, key: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class RetentionSweepResult:
    candidates: int
    deleted: int
    dry_run: bool
    enabled: bool


class MediaRetentionService:
    def __init__(
        self, storage: RetentionStorage, objects: DeletableObjects,
        policy: MediaRetentionPolicy | None = None,
    ) -> None:
        self._storage = storage
        self._objects = objects
        self._policy = policy or MediaRetentionPolicy.from_env()
        self._io = BlockingIO(4)

    async def sweep_workspace(
        self, workspace_id: int, *, now: datetime, limit: int = 100,
    ) -> RetentionSweepResult:
        if not self._policy.enabled:
            return RetentionSweepResult(0, 0, self._policy.dry_run, False)
        assets = await self._storage.list_retention_assets(workspace_id, limit)
        candidates = select_retention_candidates(
            assets,
            policy=self._policy,
            referenced_asset_ids=await self._storage.referenced_asset_ids(workspace_id),
            approved_asset_ids=await self._storage.approved_asset_ids(workspace_id),
            workspace_id=workspace_id,
            now=now,
        )
        if self._policy.dry_run:
            return RetentionSweepResult(len(candidates), 0, True, True)
        deleted = 0
        for asset in candidates:
            if not await self._storage.claim_retained_asset(asset.id, workspace_id):
                continue
            try:
                object_deleted = await self._io.run(partial(self._objects.delete, asset.storage_key))
            except BaseException:
                await self._storage.release_retained_asset(asset.id, workspace_id)
                raise
            if not object_deleted:
                await self._storage.release_retained_asset(asset.id, workspace_id)
                continue
            await self._storage.delete_retained_asset(asset.id, workspace_id)
            deleted += 1
        return RetentionSweepResult(len(candidates), deleted, False, True)
