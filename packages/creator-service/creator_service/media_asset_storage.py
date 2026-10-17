from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
import uuid

import anyio
from creator_domain.models import MediaAsset, MediaOrigin

from .media_upload_reconciliation import MediaAssetPersistenceFailed, UploadIntent, UploadIntentState
from .object_storage import ArtifactStorageBackend as MediaStorageBackend


@dataclass(frozen=True, slots=True)
class AssetPage:
    items: list[MediaAsset]
    total: int
    limit: int
    offset: int


class MediaAssetStorageBackend(Protocol):
    async def save_asset(self, row: dict[str, object]) -> dict[str, object]: ...
    async def save_uploaded_asset(
        self, row: dict[str, object], intent: UploadIntent,
    ) -> dict[str, object]: ...

    async def get_asset(self, asset_id: int, workspace_id: int) -> dict[str, object] | None: ...

    async def list_assets(
        self, workspace_id: int, *, media_type: str | None = None,
        project_id: int | None = None, limit: int, offset: int,
    ) -> tuple[list[dict[str, object]], int]: ...

    async def create_upload_intent(self, intent: UploadIntent) -> UploadIntent: ...
    async def mark_upload_intent_uploaded(self, intent_id: int) -> None: ...
    async def complete_upload_intent(
        self, intent_id: int, *, owner_id: str | None = None, claim_token: str | None = None,
    ) -> None: ...
    async def compensate_upload(self, intent: UploadIntent, deletion_failed: bool) -> None: ...
    async def asset_exists_for_key(self, workspace_id: int, storage_key: str) -> bool: ...
    async def claim_expired_upload_intents(
        self, *, now: datetime, lease_expires_at: datetime, limit: int,
    ) -> list[UploadIntent]: ...
    async def record_upload_reclaimed(self, intent_id: int, claim_token: str | None = None) -> None: ...
    async def watch_for_late_upload(
        self, intent_id: int, claim_token: str, watch_expires_at: datetime,
    ) -> None: ...
    async def record_upload_cleanup_failure(
        self, intent_id: int, max_retries: int, claim_token: str | None = None,
    ) -> bool: ...


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
        self._intents: dict[int, UploadIntent] = {}
        self._next_intent_id = 1

    async def save_asset(self, row: dict[str, object]) -> dict[str, object]:
        async with self._lock:
            saved = MediaAsset.model_validate({**row, "id": self._next_id})
            self._next_id += 1
            self._assets.append(saved.model_dump())
        return saved.model_dump()

    async def save_uploaded_asset(
        self, row: dict[str, object], intent: UploadIntent,
    ) -> dict[str, object]:
        async with self._lock:
            current = self._intents[intent.id]
            if current.state is not UploadIntentState.UPLOADED or current.owner_id != intent.owner_id:
                raise MediaAssetPersistenceFailed()
            saved = MediaAsset.model_validate({**row, "id": self._next_id})
            self._next_id += 1
            self._assets.append(saved.model_dump())
            self._set_intent(intent.id, UploadIntentState.COMPLETED)
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

    async def create_upload_intent(self, intent: UploadIntent) -> UploadIntent:
        async with self._lock:
            saved = UploadIntent(
                id=self._next_intent_id, owner_id=intent.owner_id,
                workspace_id=intent.workspace_id, storage_key=intent.storage_key,
                state=intent.state, lease_expires_at=intent.lease_expires_at,
            )
            self._intents[saved.id] = saved
            self._next_intent_id += 1
        return saved

    def _set_intent(self, intent_id: int, state: UploadIntentState, **changes: object) -> None:
        intent = self._intents[intent_id]
        self._intents[intent_id] = UploadIntent(
            id=intent.id, owner_id=intent.owner_id, workspace_id=intent.workspace_id,
            storage_key=intent.storage_key, state=state,
            lease_expires_at=changes.get("lease_expires_at", intent.lease_expires_at),
            retry_count=changes.get("retry_count", intent.retry_count),
            claim_token=changes.get("claim_token", intent.claim_token),
        )

    async def mark_upload_intent_uploaded(self, intent_id: int) -> None:
        async with self._lock:
            if self._intents[intent_id].state is not UploadIntentState.PENDING:
                raise MediaAssetPersistenceFailed()
            self._set_intent(intent_id, UploadIntentState.UPLOADED)

    async def complete_upload_intent(
        self, intent_id: int, *, owner_id: str | None = None, claim_token: str | None = None,
    ) -> None:
        async with self._lock:
            intent = self._intents[intent_id]
            uploader_owns = owner_id is not None and intent.owner_id == owner_id and intent.state is UploadIntentState.UPLOADED
            reconciler_owns = claim_token is not None and intent.claim_token == claim_token and intent.state is UploadIntentState.RECLAIMING
            if not uploader_owns and not reconciler_owns:
                raise MediaAssetPersistenceFailed()
            self._set_intent(intent_id, UploadIntentState.COMPLETED)

    async def compensate_upload(self, intent: UploadIntent, deletion_failed: bool) -> None:
        async with self._lock:
            current = self._intents[intent.id]
            if current.owner_id != intent.owner_id:
                raise MediaAssetPersistenceFailed()
            state = UploadIntentState.CLEANUP_PENDING if deletion_failed else UploadIntentState.RECLAIMED
            self._set_intent(intent.id, state)

    async def asset_exists_for_key(self, workspace_id: int, storage_key: str) -> bool:
        return any(
            asset["workspace_id"] == workspace_id and asset.get("storage_key") == storage_key
            for asset in self._assets
        )

    async def claim_expired_upload_intents(
        self, *, now: datetime, lease_expires_at: datetime, limit: int,
    ) -> list[UploadIntent]:
        async with self._lock:
            eligible = [
                intent for intent in self._intents.values()
                if intent.state in {
                    UploadIntentState.PENDING,
                    UploadIntentState.UPLOADED,
                    UploadIntentState.CLEANUP_PENDING,
                    UploadIntentState.RECLAIMING,
                    UploadIntentState.LATE_UPLOAD_WATCH,
                }
                and intent.lease_expires_at <= now
            ][:limit]
            for intent in eligible:
                self._set_intent(
                    intent.id, UploadIntentState.RECLAIMING,
                    lease_expires_at=lease_expires_at, claim_token=uuid.uuid4().hex,
                )
            return [
                UploadIntent(
                    id=intent.id, owner_id=intent.owner_id,
                    workspace_id=intent.workspace_id, storage_key=intent.storage_key,
                    state=intent.state, lease_expires_at=lease_expires_at,
                    retry_count=intent.retry_count,
                    claim_token=self._intents[intent.id].claim_token,
                )
                for intent in eligible
            ]

    async def record_upload_reclaimed(self, intent_id: int, claim_token: str | None = None) -> None:
        async with self._lock:
            intent = self._intents[intent_id]
            if claim_token is not None and (
                intent.state is not UploadIntentState.RECLAIMING or intent.claim_token != claim_token
            ):
                raise MediaAssetPersistenceFailed()
            self._set_intent(intent_id, UploadIntentState.RECLAIMED)

    async def watch_for_late_upload(
        self, intent_id: int, claim_token: str, watch_expires_at: datetime,
    ) -> None:
        async with self._lock:
            intent = self._intents[intent_id]
            if intent.state is not UploadIntentState.RECLAIMING or intent.claim_token != claim_token:
                raise MediaAssetPersistenceFailed()
            self._set_intent(
                intent_id, UploadIntentState.LATE_UPLOAD_WATCH,
                lease_expires_at=watch_expires_at,
            )

    async def record_upload_cleanup_failure(
        self, intent_id: int, max_retries: int, claim_token: str | None = None,
    ) -> bool:
        async with self._lock:
            intent = self._intents[intent_id]
            if claim_token is not None and (
                intent.state is not UploadIntentState.RECLAIMING or intent.claim_token != claim_token
            ):
                raise MediaAssetPersistenceFailed()
            retries = intent.retry_count + 1
            exhausted = retries >= max_retries
            self._set_intent(
                intent_id,
                UploadIntentState.EXHAUSTED if exhausted else UploadIntentState.CLEANUP_PENDING,
                retry_count=retries,
            )
        return exhausted

    async def list_upload_intents(self) -> list[UploadIntent]:
        return list(self._intents.values())

    async def expire_upload_intent(self, intent_id: int, now: datetime) -> None:
        async with self._lock:
            intent = self._intents[intent_id]
            self._set_intent(intent_id, intent.state, lease_expires_at=now)
