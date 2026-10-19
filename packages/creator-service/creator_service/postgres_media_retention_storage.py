from __future__ import annotations

import json
from datetime import timedelta
from typing import Final
import uuid

from . import db
from .media_retention import RetentionAsset

_CLAIM_LEASE: Final = timedelta(minutes=15)


class PostgresMediaRetentionStorage:
    async def list_retention_workspaces(
        self, limit: int, *, after_workspace_id: int | None = None,
    ) -> list[int]:
        rows = await db.fetch_all(
            """SELECT DISTINCT workspace_id FROM creator_media_assets
                WHERE ($2::bigint IS NULL OR workspace_id > $2)
                ORDER BY workspace_id LIMIT $1""",
            limit, after_workspace_id,
        )
        return [int(row["workspace_id"]) for row in rows]

    async def list_retention_assets(
        self, workspace_id: int, limit: int, *, after: RetentionAsset | None = None,
    ) -> list[RetentionAsset]:
        pool = await db.get_pool()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute(
                """DELETE FROM creator_media_asset_deletion_claims
                    WHERE workspace_id = $1 AND lease_expires_at <= now()""",
                workspace_id,
            )
            rows = await connection.fetch(
                """SELECT id, workspace_id, storage_key, origin, media_type, created_at
                FROM creator_media_assets
                WHERE workspace_id = $1 AND storage_key IS NOT NULL
                AND ($3::timestamptz IS NULL OR (created_at, id) > ($3, $4))
                AND NOT EXISTS (
                    SELECT 1 FROM creator_media_asset_deletion_claims deletion
                    WHERE deletion.asset_id = creator_media_assets.id
                )
                ORDER BY created_at, id LIMIT $2""",
                workspace_id, limit,
                after.created_at if after is not None else None,
                after.id if after is not None else None,
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
            """SELECT DISTINCT asset_id FROM (
                    SELECT asset_id
                    FROM creator_approved_timeline_assets WHERE workspace_id = $1
                    UNION ALL
                    SELECT (segment->>'asset_id')::bigint AS asset_id
                    FROM creator_stage_reviews review
                    JOIN creator_runs run ON run.id = review.run_id
                    JOIN creator_timelines timeline
                      ON timeline.project_id = run.project_id
                     AND timeline.workspace_id = run.workspace_id
                     AND timeline.timeline_id = review.notes::jsonb->>'timeline_id'
                     AND timeline.revision = (review.notes::jsonb->>'revision')::integer
                    CROSS JOIN LATERAL
                        jsonb_array_elements(timeline.segments_json::jsonb) segment
                    WHERE run.workspace_id = $1
                      AND review.stage_name = 'TIMELINE_REVIEW'
                      AND review.review_status = 'approved'
                      AND NOT EXISTS (
                          SELECT 1 FROM creator_approved_timeline_assets mapped
                          WHERE mapped.review_id = review.id
                      )
                ) approved""",
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

    async def delete_retained_asset(
        self, asset_id: int, workspace_id: int, claim_token: str,
    ) -> None:
        await db.execute(
            """DELETE FROM creator_media_assets
                WHERE id = $1 AND workspace_id = $2
                AND EXISTS (
                    SELECT 1 FROM creator_media_asset_deletion_claims deletion
                    WHERE deletion.asset_id = creator_media_assets.id
                    AND deletion.claim_token = $3
                )""",
            asset_id, workspace_id, claim_token,
        )

    async def claim_retained_asset(self, asset_id: int, workspace_id: int) -> str | None:
        claim_token = uuid.uuid4().hex
        pool = await db.get_pool()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
            claimed = await connection.fetchval(
                """INSERT INTO creator_media_asset_deletion_claims (
                        asset_id, workspace_id, claim_token, lease_expires_at
                    )
                    SELECT a.id, a.workspace_id, $3, now() + $4 FROM creator_media_assets a
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
                asset_id, workspace_id, claim_token, _CLAIM_LEASE,
            )
        return claim_token if claimed is not None else None

    async def release_retained_asset(
        self, asset_id: int, workspace_id: int, claim_token: str,
    ) -> None:
        await db.execute(
            """DELETE FROM creator_media_asset_deletion_claims
                WHERE asset_id = $1 AND workspace_id = $2 AND claim_token = $3""",
            asset_id, workspace_id, claim_token,
        )
