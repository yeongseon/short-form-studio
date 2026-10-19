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
            """SELECT DISTINCT a.id FROM creator_media_assets a
                JOIN creator_runs r ON r.project_id = a.project_id
                    AND r.workspace_id = a.workspace_id
                JOIN creator_stage_reviews s ON s.run_id = r.id
                WHERE a.workspace_id = $1 AND s.review_status = 'approved'""",
            workspace_id,
        )
        return frozenset(int(row["id"]) for row in rows)

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
            "DELETE FROM creator_media_assets WHERE id = $1 AND workspace_id = $2",
            asset_id, workspace_id,
        )
