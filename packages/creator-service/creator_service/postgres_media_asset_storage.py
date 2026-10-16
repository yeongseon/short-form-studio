from __future__ import annotations

import json
import asyncpg
from creator_domain.models import MediaAsset
from pydantic import TypeAdapter

from . import db
from .media_upload_reconciliation import (
    MediaAssetPersistenceFailed,
    MediaAssetPersistenceIndeterminate,
    UploadIntent,
)
from .storage_policy import StoragePolicy, StorageUsage, ensure_budget
from .postgres_media_retention_storage import PostgresMediaRetentionStorage
from .postgres_upload_intent_storage import PostgresUploadIntentStorage, _decode_intent

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


class PostgresMediaAssetStorage(PostgresUploadIntentStorage, PostgresMediaRetentionStorage):
    async def get_storage_usage(
        self, workspace_id: int, *, policy: StoragePolicy | None = None,
    ) -> StorageUsage:
        active_policy = policy or StoragePolicy()
        row = await db.fetch_one(
            """SELECT
                COALESCE((SELECT SUM((metadata->>'size_bytes')::bigint)
                    FROM creator_media_assets WHERE workspace_id = $1), 0) AS stored_bytes,
                (SELECT COUNT(*) FROM creator_media_assets WHERE workspace_id = $1) AS stored_assets,
                COALESCE((SELECT SUM(reserved_bytes) FROM creator_media_upload_intents
                    WHERE workspace_id = $1
                    AND state IN ('pending', 'uploaded', 'cleanup_pending')), 0) AS reserved_bytes,
                (SELECT COUNT(*) FROM creator_media_upload_intents WHERE workspace_id = $1
                    AND state IN ('pending', 'uploaded', 'cleanup_pending')) AS reserved_assets""",
            workspace_id,
        )
        if row is None:
            raise MediaAssetPersistenceFailed()
        return StorageUsage(
            stored_bytes=int(row["stored_bytes"]),
            stored_asset_count=int(row["stored_assets"]),
            reserved_bytes=int(row["reserved_bytes"]),
            reserved_asset_count=int(row["reserved_assets"]),
            max_stored_bytes=active_policy.max_stored_bytes,
            max_asset_count=active_policy.max_asset_count,
            max_reserved_bytes=active_policy.max_reserved_bytes,
        )
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
                if saved is None:
                    raise MediaAssetPersistenceFailed()
        except MediaAssetPersistenceFailed:
            raise
        except (OSError, asyncpg.PostgresConnectionError, asyncpg.InterfaceError) as error:
            raise MediaAssetPersistenceIndeterminate() from error
        except asyncpg.PostgresError as error:
            raise MediaAssetPersistenceFailed() from error
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
    async def create_upload_intent(
        self, intent: UploadIntent, *, policy: StoragePolicy | None = None,
    ) -> UploadIntent:
        active_policy = policy or StoragePolicy()
        pool = await db.get_pool()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock($1)", intent.workspace_id)
            usage_row = await connection.fetchrow(
                """SELECT
                    COALESCE(SUM((metadata->>'size_bytes')::bigint), 0) AS stored_bytes,
                    COUNT(*) AS stored_assets
                    FROM creator_media_assets WHERE workspace_id = $1""",
                intent.workspace_id,
            )
            reserved_row = await connection.fetchrow(
                """SELECT COALESCE(SUM(reserved_bytes), 0) AS reserved_bytes,
                    COUNT(*) AS reserved_assets
                    FROM creator_media_upload_intents
                    WHERE workspace_id = $1
                    AND state IN ('pending', 'uploaded', 'cleanup_pending')""",
                intent.workspace_id,
            )
            usage = StorageUsage(
                stored_bytes=int(usage_row["stored_bytes"]),
                stored_asset_count=int(usage_row["stored_assets"]),
                reserved_bytes=int(reserved_row["reserved_bytes"]),
                reserved_asset_count=int(reserved_row["reserved_assets"]),
                max_stored_bytes=active_policy.max_stored_bytes,
                max_asset_count=active_policy.max_asset_count,
                max_reserved_bytes=active_policy.max_reserved_bytes,
            )
            ensure_budget(
                workspace_id=intent.workspace_id,
                incoming_bytes=intent.reserved_bytes,
                usage=usage,
                policy=active_policy,
            )
            row = await connection.fetchrow(
                """INSERT INTO creator_media_upload_intents
                    (owner_id, workspace_id, storage_key, state, lease_expires_at, reserved_bytes)
                    VALUES ($1, $2, $3, $4, $5, $6) RETURNING *""",
                intent.owner_id, intent.workspace_id, intent.storage_key,
                intent.state.value, intent.lease_expires_at, intent.reserved_bytes,
            )
        if row is None:
            raise MediaAssetPersistenceFailed()
        return _decode_intent(row)
