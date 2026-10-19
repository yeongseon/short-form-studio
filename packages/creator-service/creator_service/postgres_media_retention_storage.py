from __future__ import annotations

import json

from . import db
from .media_retention import RetentionAsset


class PostgresMediaRetentionStorage:
    async def list_retention_workspaces(self, limit: int) -> list[int]:
        rows = await db.fetch_all(
            "SELECT DISTINCT workspace_id FROM creator_media_assets ORDER BY workspace_id LIMIT $1",
            limit,
        )
        return [int(row["workspace_id"]) for row in rows]

    async def list_retention_assets(self, workspace_id: int, limit: int) -> list[RetentionAsset]:
        rows = await db.fetch_all(
            """SELECT id, workspace_id, storage_key, origin, media_type, created_at
                FROM creator_media_assets
                WHERE workspace_id = $1 AND storage_key IS NOT NULL
                AND NOT EXISTS (
                    SELECT 1 FROM creator_media_asset_deletion_claims deletion
                    WHERE deletion.asset_id = creator_media_assets.id
                )
                ORDER BY created_at, id LIMIT $2""",
            workspace_id, limit,
        )
        return [
            RetentionAsset(
                id=int(row["id"]), workspace_id=int(row["workspace_id"]),
                storage_key=str(row["storage_key"]), origin=str(row["origin"]),
                media_type=str(row["media_type"]), created_at=row["created_at"],
            )
            for row in rows
        ]

    async def referenced_asset_ids(self, workspace_id: int) -> frozenset[int]:
        return await self._timeline_asset_ids(workspace_id)

    async def approved_asset_ids(self, workspace_id: int) -> frozenset[int]:
        rows = await db.fetch_all(
            """SELECT DISTINCT asset_id
                FROM creator_approved_timeline_assets WHERE workspace_id = $1""",
            workspace_id,
        )
        return frozenset(int(row["asset_id"]) for row in rows)

    async def _timeline_asset_ids(self, workspace_id: int) -> frozenset[int]:
        rows = await db.fetch_all(
            "SELECT segments_json FROM creator_timelines WHERE workspace_id = $1",
            workspace_id,
        )
        asset_ids: set[int] = set()
        for row in rows:
            segments = json.loads(str(row["segments_json"]))
            for segment in segments:
                if isinstance(segment, dict) and isinstance(segment.get("asset_id"), int):
                    asset_ids.add(segment["asset_id"])
        return frozenset(asset_ids)

    async def delete_retained_asset(self, asset_id: int, workspace_id: int) -> None:
        await db.execute(
            """DELETE FROM creator_media_assets
                WHERE id = $1 AND workspace_id = $2
                AND EXISTS (
                    SELECT 1 FROM creator_media_asset_deletion_claims deletion
                    WHERE deletion.asset_id = creator_media_assets.id
                )""",
            asset_id, workspace_id,
        )

    async def claim_retained_asset(self, asset_id: int, workspace_id: int) -> bool:
        pool = await db.get_pool()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
            claimed = await connection.fetchval(
                """INSERT INTO creator_media_asset_deletion_claims (asset_id, workspace_id)
                    SELECT a.id, a.workspace_id FROM creator_media_assets a
                    WHERE a.id = $1 AND a.workspace_id = $2
                    AND NOT EXISTS (
                        SELECT 1 FROM creator_media_asset_deletion_claims deletion
                        WHERE deletion.asset_id = a.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM creator_timelines t
                        CROSS JOIN LATERAL jsonb_array_elements(t.segments_json::jsonb) segment
                        WHERE t.workspace_id = $2
                        AND (segment->>'asset_id')::bigint = a.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM creator_approved_timeline_assets approved
                        WHERE approved.workspace_id = $2 AND approved.asset_id = a.id
                    ) RETURNING asset_id""",
                asset_id, workspace_id,
            )
        return claimed is not None

    async def release_retained_asset(self, asset_id: int, workspace_id: int) -> None:
        await db.execute(
            """DELETE FROM creator_media_asset_deletion_claims
                WHERE asset_id = $1 AND workspace_id = $2""",
            asset_id, workspace_id,
        )
