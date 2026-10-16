from __future__ import annotations

import uuid
from datetime import datetime

from . import db
from .media_upload_reconciliation import (
    MediaAssetPersistenceFailed,
    UploadIntent,
    UploadIntentState,
)


class PostgresUploadIntentStorage:
    async def create_upload_intent(self, intent: UploadIntent) -> UploadIntent:
        row = await db.fetch_one(
            """INSERT INTO creator_media_upload_intents
                (owner_id, workspace_id, storage_key, state, lease_expires_at, reserved_bytes)
                VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
            intent.owner_id, intent.workspace_id, intent.storage_key,
            intent.state.value, intent.lease_expires_at, intent.reserved_bytes,
        )
        if row is None:
            raise MediaAssetPersistenceFailed()
        return _decode_intent(row)

    async def mark_upload_intent_uploaded(self, intent_id: int) -> None:
        result = await db.execute(
            """UPDATE creator_media_upload_intents SET state = 'uploaded', updated_at = NOW()
                WHERE id = $1 AND state = 'pending'""",
            intent_id,
        )
        if result != "UPDATE 1":
            raise MediaAssetPersistenceFailed()

    async def complete_upload_intent(
        self, intent_id: int, *, owner_id: str | None = None, claim_token: str | None = None,
    ) -> None:
        result = await db.execute(
            """UPDATE creator_media_upload_intents SET state = 'completed', updated_at = NOW()
                WHERE id = $1 AND (
                    ($2::text IS NOT NULL AND owner_id = $2 AND state = 'uploaded') OR
                    ($3::text IS NOT NULL AND claim_token = $3 AND state = 'reclaiming')
                )""",
            intent_id, owner_id, claim_token,
        )
        if result != "UPDATE 1":
            raise MediaAssetPersistenceFailed()

    async def compensate_upload(self, intent: UploadIntent, deletion_failed: bool) -> None:
        state = UploadIntentState.CLEANUP_PENDING if deletion_failed else UploadIntentState.RECLAIMED
        result = await db.execute(
            """UPDATE creator_media_upload_intents SET state = $3, updated_at = NOW()
                WHERE id = $1 AND owner_id = $2""",
            intent.id, intent.owner_id, state.value,
        )
        if result != "UPDATE 1":
            raise MediaAssetPersistenceFailed()

    async def asset_exists_for_key(self, workspace_id: int, storage_key: str) -> bool:
        return await db.fetch_one(
            """SELECT id FROM creator_media_assets
                WHERE workspace_id = $1 AND storage_key = $2""",
            workspace_id, storage_key,
        ) is not None

    async def claim_expired_upload_intents(
        self, *, now: datetime, lease_expires_at: datetime, limit: int,
    ) -> list[UploadIntent]:
        pool = await db.get_pool()
        async with pool.acquire() as connection, connection.transaction():
            rows = await connection.fetch(
                """SELECT * FROM creator_media_upload_intents
                    WHERE state IN (
                        'pending', 'uploaded', 'cleanup_pending', 'reclaiming',
                        'late_upload_watch'
                    ) AND lease_expires_at <= $1
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT $2""",
                now, limit,
            )
            ids = [row["id"] for row in rows]
            updated = []
            if ids:
                tokens = [uuid.uuid4().hex for _ in ids]
                updated = await connection.fetch(
                    """UPDATE creator_media_upload_intents
                        SET state = 'reclaiming', lease_expires_at = $2,
                            claim_token = claims.token, updated_at = NOW()
                        FROM unnest($1::bigint[], $3::text[]) AS claims(id, token)
                        WHERE creator_media_upload_intents.id = claims.id
                        RETURNING creator_media_upload_intents.*""",
                    ids, lease_expires_at, tokens,
                )
        claims_by_id = {int(row["id"]): str(row["claim_token"]) for row in updated}
        return [
            UploadIntent(
                id=int(row["id"]), owner_id=str(row["owner_id"]),
                workspace_id=int(row["workspace_id"]), storage_key=str(row["storage_key"]),
                state=UploadIntentState(str(row["state"])),
                lease_expires_at=lease_expires_at, retry_count=int(row["retry_count"]),
                claim_token=claims_by_id[int(row["id"])], created_at=row["created_at"],
            )
            for row in rows
        ]

    async def record_upload_reclaimed(self, intent_id: int, claim_token: str | None = None) -> None:
        if claim_token is None:
            await db.execute(
                """UPDATE creator_media_upload_intents SET state = 'reclaimed', updated_at = NOW()
                    WHERE id = $1 AND state = 'uploaded'""",
                intent_id,
            )
            return
        result = await db.execute(
            """UPDATE creator_media_upload_intents SET state = 'reclaimed', updated_at = NOW()
                WHERE id = $1 AND state = 'reclaiming' AND claim_token = $2""",
            intent_id, claim_token,
        )
        if result != "UPDATE 1":
            raise MediaAssetPersistenceFailed()

    async def watch_for_late_upload(
        self, intent_id: int, claim_token: str, watch_expires_at: datetime,
    ) -> None:
        result = await db.execute(
            """UPDATE creator_media_upload_intents
                SET state = 'late_upload_watch', lease_expires_at = $3, updated_at = NOW()
                WHERE id = $1 AND state = 'reclaiming' AND claim_token = $2""",
            intent_id, claim_token, watch_expires_at,
        )
        if result != "UPDATE 1":
            raise MediaAssetPersistenceFailed()

    async def record_upload_cleanup_failure(
        self, intent_id: int, max_retries: int, claim_token: str | None = None,
    ) -> bool:
        row = await db.fetch_one(
            """UPDATE creator_media_upload_intents
                SET retry_count = retry_count + 1,
                    state = CASE WHEN retry_count + 1 >= $2 THEN 'exhausted' ELSE 'cleanup_pending' END,
                    updated_at = NOW()
                WHERE id = $1 AND ($3::text IS NULL OR
                    (state = 'reclaiming' AND claim_token = $3)) RETURNING state""",
            intent_id, max_retries, claim_token,
        )
        if row is None and claim_token is not None:
            raise MediaAssetPersistenceFailed()
        return row is not None and row["state"] == UploadIntentState.EXHAUSTED.value


def _decode_intent(row: dict[str, object]) -> UploadIntent:
    lease_expires_at = row["lease_expires_at"]
    if not isinstance(lease_expires_at, datetime):
        raise MediaAssetPersistenceFailed()
    return UploadIntent(
        id=int(row["id"]), owner_id=str(row["owner_id"]),
        workspace_id=int(row["workspace_id"]), storage_key=str(row["storage_key"]),
        state=UploadIntentState(str(row["state"])),
        lease_expires_at=lease_expires_at, retry_count=int(row["retry_count"]),
        claim_token=str(row["claim_token"]) if row.get("claim_token") is not None else None,
        created_at=row["created_at"], reserved_bytes=int(row["reserved_bytes"]),
    )
