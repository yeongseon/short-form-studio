from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from functools import partial
from typing import Final, Protocol

from .blocking_io import BlockingIO
from .object_storage import StorageDeletionError

logger = logging.getLogger(__name__)
DEFAULT_UPLOAD_LEASE: Final = timedelta(minutes=30)
DEFAULT_SWEEP_LEASE: Final = timedelta(minutes=5)


class MediaAssetPersistenceFailed(RuntimeError):
    """Metadata transaction definitely did not commit."""


class MediaAssetPersistenceIndeterminate(RuntimeError):
    """Metadata commit acknowledgement was lost."""


class UploadIntentState(StrEnum):
    PENDING = "pending"
    UPLOADED = "uploaded"
    CLEANUP_PENDING = "cleanup_pending"
    RECLAIMING = "reclaiming"
    COMPLETED = "completed"
    RECLAIMED = "reclaimed"
    EXHAUSTED = "exhausted"


@dataclass(frozen=True, slots=True)
class UploadIntent:
    id: int
    owner_id: str
    workspace_id: int
    storage_key: str
    state: UploadIntentState
    lease_expires_at: datetime
    retry_count: int = 0
    claim_token: str | None = None


@dataclass(frozen=True, slots=True)
class SweepResult:
    reclaimed: int
    preserved: int
    failed: int
    exhausted: int


class UploadIntentStorage(Protocol):
    async def create_upload_intent(self, intent: UploadIntent) -> UploadIntent: ...
    async def mark_upload_intent_uploaded(self, intent_id: int) -> None: ...
    async def complete_upload_intent(
        self, intent_id: int, *, owner_id: str | None = None, claim_token: str | None = None,
    ) -> None: ...
    async def defer_upload_cleanup(self, intent_id: int) -> None: ...
    async def asset_exists_for_key(self, workspace_id: int, storage_key: str) -> bool: ...
    async def claim_expired_upload_intents(
        self, *, now: datetime, lease_expires_at: datetime, limit: int,
    ) -> list[UploadIntent]: ...
    async def record_upload_reclaimed(self, intent_id: int, claim_token: str | None = None) -> None: ...
    async def record_upload_cleanup_failure(
        self, intent_id: int, max_retries: int, claim_token: str | None = None,
    ) -> bool: ...


class DeletableStorage(Protocol):
    def delete(self, key: str) -> bool: ...


class MediaUploadReconciler:
    def __init__(
        self, objects: DeletableStorage, intents: UploadIntentStorage,
        *, max_retries: int = 5, batch_size: int = 100,
    ) -> None:
        self._objects = objects
        self._intents = intents
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._io = BlockingIO(4)

    async def sweep(self, *, now: datetime | None = None) -> SweepResult:
        swept_at = now or datetime.now(timezone.utc)
        claimed = await self._intents.claim_expired_upload_intents(
            now=swept_at,
            lease_expires_at=swept_at + DEFAULT_SWEEP_LEASE,
            limit=self._batch_size,
        )
        reclaimed = preserved = failed = exhausted = 0
        for intent in claimed:
            if await self._intents.asset_exists_for_key(intent.workspace_id, intent.storage_key):
                await self._intents.complete_upload_intent(
                    intent.id, claim_token=intent.claim_token,
                )
                preserved += 1
                continue
            try:
                await self._io.run(partial(self._objects.delete, intent.storage_key))
            except StorageDeletionError:
                is_exhausted = await self._intents.record_upload_cleanup_failure(
                    intent.id, self._max_retries,
                    intent.claim_token,
                )
                logger.warning(
                    "media_upload.cleanup_failed intent_id=%s workspace_id=%s retry=%s exhausted=%s",
                    intent.id, intent.workspace_id, intent.retry_count + 1, is_exhausted,
                )
                failed += 1
                exhausted += int(is_exhausted)
                continue
            await self._intents.record_upload_reclaimed(intent.id, intent.claim_token)
            reclaimed += 1
        return SweepResult(reclaimed, preserved, failed, exhausted)
