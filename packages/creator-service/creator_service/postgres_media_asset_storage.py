from __future__ import annotations

import json
import uuid
from datetime import datetime

import asyncpg
from creator_domain.models import MediaAsset
from pydantic import TypeAdapter

from . import db
from .media_upload_reconciliation import (
    MediaAssetPersistenceFailed,
    MediaAssetPersistenceIndeterminate,
    UploadIntent,
    UploadIntentState,
)

_METADATA = TypeAdapter(dict[str, object])
_FILTER = """
    workspace_id = $1
    AND ($2::text IS NULL OR media_type = $2)
    AND ($3::integer IS NULL OR project_id = $3)
"""
_ORDER = """
    CASE origin WHEN 'UPLOADED' THEN 0 WHEN 'IMPORTED' THEN 1
        WHEN 'EXTERNAL_URL' THEN 2 WHEN 'STOCK' THEN 3 WHEN 'GENERATED' THEN 4
        ELSE 5 END,
    created_at DESC, id DESC
"""


class MediaAssetAssociationRejected(MediaAssetPersistenceFailed, ValueError):
    """A referenced project or run does not belong to the asset's workspace/project."""


def _decode_asset(row: dict[str, object]) -> dict[str, object]:
    metadata = row["metadata"]
    if isinstance(metadata, str):
        metadata = _METADATA.validate_json(metadata)
    return MediaAsset.model_validate({**row, "metadata": metadata}).model_dump()


class PostgresMediaAssetStorage:
    async def save_asset(self, row: dict[str, object]) -> dict[str, object]:
        asset = MediaAsset.model_validate({**row, "id": 1})
        try:
            saved = await db.fetch_one("""
            INSERT INTO creator_media_assets (
                workspace_id, project_id, run_id, media_type, origin, storage_key,
                mime_type, width, height, duration_seconds, source_url, metadata, created_at
            )
            SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13
            WHERE ($2::integer IS NULL OR EXISTS (
                SELECT 1 FROM creator_projects WHERE id = $2 AND workspace_id = $1
            )) AND ($3::integer IS NULL OR EXISTS (
                SELECT 1 FROM creator_runs WHERE id = $3 AND workspace_id = $1
                    AND ($2::integer IS NULL OR project_id = $2)
            ))
            RETURNING *
            """,
            asset.workspace_id, asset.project_id, asset.run_id, asset.media_type.value,
            asset.origin.value, asset.storage_key, asset.mime_type, asset.width, asset.height,
            asset.duration_seconds, asset.source_url,
            json.dumps(asset.metadata, allow_nan=False), asset.created_at,
            )
        except (OSError, asyncpg.PostgresConnectionError, asyncpg.InterfaceError) as error:
            raise MediaAssetPersistenceIndeterminate() from error
        except asyncpg.PostgresError as error:
            raise MediaAssetPersistenceFailed() from error
        if saved is None:
            raise MediaAssetAssociationRejected("Media asset association not found")
        return _decode_asset(saved)

    async def save_uploaded_asset(
        self, row: dict[str, object], intent: UploadIntent,
    ) -> dict[str, object]:
        asset = MediaAsset.model_validate({**row, "id": 1})
        try:
            pool = await db.get_pool()
            async with pool.acquire() as connection, connection.transaction():
                claimed = await connection.fetchval(
                    """UPDATE creator_media_upload_intents
                        SET state = 'completed', updated_at = NOW()
                        WHERE id = $1 AND owner_id = $2 AND state = 'uploaded'
                        RETURNING id""",
                    intent.id, intent.owner_id,
                )
                if claimed is None:
                    raise MediaAssetPersistenceFailed()
                saved = await connection.fetchrow(
                    """INSERT INTO creator_media_assets (
                        workspace_id, project_id, run_id, media_type, origin, storage_key,
                        mime_type, width, height, duration_seconds, source_url, metadata, created_at
                    ) SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13
                    WHERE ($2::integer IS NULL OR EXISTS (
                        SELECT 1 FROM creator_projects WHERE id = $2 AND workspace_id = $1
                    )) AND ($3::integer IS NULL OR EXISTS (
                        SELECT 1 FROM creator_runs WHERE id = $3 AND workspace_id = $1
                            AND ($2::integer IS NULL OR project_id = $2)
                    ))
                    RETURNING *""",
                    asset.workspace_id, asset.project_id, asset.run_id, asset.media_type.value,
                    asset.origin.value, asset.storage_key, asset.mime_type, asset.width,
                    asset.height, asset.duration_seconds, asset.source_url,
                    json.dumps(asset.metadata, allow_nan=False), asset.created_at,
                )
        except MediaAssetPersistenceFailed:
            raise
        except (OSError, asyncpg.PostgresConnectionError, asyncpg.InterfaceError) as error:
            raise MediaAssetPersistenceIndeterminate() from error
        except asyncpg.PostgresError as error:
            raise MediaAssetPersistenceFailed() from error
        if saved is None:
            raise MediaAssetPersistenceFailed()
        return _decode_asset(dict(saved))

    async def get_asset(self, asset_id: int, workspace_id: int) -> dict[str, object] | None:
        row = await db.fetch_one(
            "SELECT * FROM creator_media_assets WHERE id = $1 AND workspace_id = $2",
            asset_id, workspace_id,
        )
        return _decode_asset(row) if row is not None else None

    async def list_assets(
        self, workspace_id: int, *, media_type: str | None = None,
        project_id: int | None = None, limit: int, offset: int,
    ) -> tuple[list[dict[str, object]], int]:
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                total = await connection.fetchval(
                    f"SELECT count(*) FROM creator_media_assets WHERE {_FILTER}",
                    workspace_id, media_type, project_id,
                )
                rows = await connection.fetch(
                    f"""SELECT * FROM creator_media_assets WHERE {_FILTER}
                        ORDER BY {_ORDER} LIMIT $4 OFFSET $5""",
                    workspace_id, media_type, project_id, limit, offset,
                )
        return [_decode_asset(dict(row)) for row in rows], int(total)

    async def create_upload_intent(self, intent: UploadIntent) -> UploadIntent:
        row = await db.fetch_one(
            """INSERT INTO creator_media_upload_intents
                (owner_id, workspace_id, storage_key, state, lease_expires_at)
                VALUES ($1, $2, $3, $4, $5) RETURNING *""",
            intent.owner_id, intent.workspace_id, intent.storage_key,
            intent.state.value, intent.lease_expires_at,
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

    async def defer_upload_cleanup(self, intent_id: int) -> None:
        await db.execute(
            """UPDATE creator_media_upload_intents SET state = 'cleanup_pending', updated_at = NOW()
                WHERE id = $1 AND state = 'uploaded'""",
            intent_id,
        )

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
                    WHERE state IN ('pending', 'uploaded', 'cleanup_pending')
                      AND lease_expires_at <= $1
                    ORDER BY id FOR UPDATE SKIP LOCKED LIMIT $2""",
                now, limit,
            )
            ids = [row["id"] for row in rows]
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
            else:
                updated = []
        return [_decode_intent(dict(row)) for row in updated]

    async def record_upload_reclaimed(self, intent_id: int, claim_token: str | None = None) -> None:
        if claim_token is None:
            await db.execute(
                """UPDATE creator_media_upload_intents SET state = 'reclaimed', updated_at = NOW()
                    WHERE id = $1 AND state = 'uploaded'""",
                intent_id,
            )
            return
        await db.execute(
            """UPDATE creator_media_upload_intents SET state = 'reclaimed', updated_at = NOW()
                WHERE id = $1 AND state = 'reclaiming' AND claim_token = $2""",
            intent_id, claim_token,
        )

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
    )
