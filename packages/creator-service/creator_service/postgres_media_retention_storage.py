from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
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
            rows = await connection.fetch(
                """SELECT id, workspace_id, storage_key, origin, media_type, created_at
                FROM creator_media_assets
                WHERE workspace_id = $1 AND storage_key IS NOT NULL
                AND ($3::timestamptz IS NULL OR (created_at, id) > ($3, $4))
                AND NOT EXISTS (
                    SELECT 1 FROM creator_media_asset_deletion_claims deletion
                    WHERE deletion.asset_id = creator_media_assets.id
                      AND deletion.lease_expires_at > now()
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
            "SELECT asset_id FROM creator_approved_timeline_assets WHERE workspace_id = $1",
            workspace_id,
        )
        approved = {int(row["asset_id"]) for row in rows}
        legacy_reviews = await db.fetch_all(
            """SELECT review.notes
                FROM creator_stage_reviews review
                JOIN creator_runs run ON run.id = review.run_id
                WHERE run.workspace_id = $1
                  AND review.stage_name = 'TIMELINE_REVIEW'
                  AND review.review_status = 'approved'
                  AND NOT EXISTS (
                      SELECT 1 FROM creator_resolved_timeline_approvals resolved
                      WHERE resolved.review_id = review.id
                  )""",
            workspace_id,
        )
        for review in legacy_reviews:
            timeline = await self._legacy_approved_timeline(workspace_id, review["notes"])
            if timeline is None:
                return approved | await self._timeline_asset_ids(workspace_id)
            approved.update(timeline)
        return frozenset(approved)

    async def retention_approvals_resolved(self, workspace_id: int) -> bool:
        unresolved = await db.fetch_one(
            """SELECT 1 FROM creator_media_retention_unresolved_workspaces
                WHERE workspace_id = $1
                UNION ALL
                SELECT 1 FROM creator_stage_reviews review
                JOIN creator_runs run ON run.id = review.run_id
                WHERE run.workspace_id = $1
                  AND review.stage_name = 'TIMELINE_REVIEW'
                  AND review.review_status = 'approved'
                  AND NOT EXISTS (
                      SELECT 1 FROM creator_resolved_timeline_approvals resolved
                      WHERE resolved.review_id = review.id
                  ) LIMIT 1""",
            workspace_id,
        )
        return unresolved is None

    async def _legacy_approved_timeline(
        self, workspace_id: int, notes: str | None,
    ) -> frozenset[int] | None:
        if notes is None:
            return None
        try:
            payload = json.loads(notes)
            timeline_id = payload["timeline_id"]
            revision = int(payload["revision"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
        if not isinstance(timeline_id, str):
            return None
        rows = await db.fetch_all(
            """SELECT segments_json FROM creator_timelines
                WHERE workspace_id = $1 AND timeline_id = $2 AND revision = $3""",
            workspace_id, timeline_id, revision,
        )
        asset_ids: set[int] = set()
        for row in rows:
            for segment in json.loads(str(row["segments_json"])):
                if isinstance(segment, dict) and isinstance(segment.get("asset_id"), int):
                    asset_ids.add(segment["asset_id"])
        return frozenset(asset_ids)

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

    async def claim_retained_asset(self, asset_id: int, workspace_id: int) -> str | None:
        claim_token = uuid.uuid4().hex
        pool = await db.get_pool()
        async with pool.acquire() as connection, connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
            claimed = await connection.fetchval(
                """INSERT INTO creator_media_asset_deletion_claims (
                        asset_id, workspace_id, claim_token, lease_expires_at, object_deleting
                    )
                    SELECT a.id, a.workspace_id, $3, now() + $4, false
                    FROM creator_media_assets a
                    WHERE a.id = $1 AND a.workspace_id = $2
                    AND NOT EXISTS (
                        SELECT 1 FROM creator_timelines t
                        CROSS JOIN LATERAL jsonb_array_elements(t.segments_json::jsonb) segment
                        WHERE t.workspace_id = $2
                        AND (segment->>'asset_id')::bigint = a.id
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM creator_approved_timeline_assets approved
                        WHERE approved.workspace_id = $2 AND approved.asset_id = a.id
                    )
                    ON CONFLICT (asset_id) DO UPDATE
                    SET claim_token = EXCLUDED.claim_token,
                        lease_expires_at = EXCLUDED.lease_expires_at
                    WHERE creator_media_asset_deletion_claims.workspace_id = EXCLUDED.workspace_id
                      AND creator_media_asset_deletion_claims.lease_expires_at <= now()
                    RETURNING asset_id""",
                asset_id, workspace_id, claim_token, _CLAIM_LEASE,
            )
        return claim_token if claimed is not None else None

    async def finalize_retained_asset(
        self, asset_id: int, workspace_id: int, claim_token: str,
        delete_object: Callable[[], Awaitable[None]],
    ) -> bool:
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                claim_is_valid = await connection.fetchval(
                    """SELECT EXISTS (
                        SELECT 1 FROM creator_media_asset_deletion_claims deletion
                        WHERE deletion.asset_id = $1 AND deletion.workspace_id = $2
                          AND deletion.claim_token = $3 AND deletion.lease_expires_at > now()
                          AND NOT EXISTS (
                              SELECT 1 FROM creator_timelines timeline
                              CROSS JOIN LATERAL
                                  jsonb_array_elements(timeline.segments_json::jsonb) segment
                              WHERE timeline.workspace_id = $2
                                AND (segment->>'asset_id')::bigint = deletion.asset_id
                          )
                          AND NOT EXISTS (
                              SELECT 1 FROM creator_approved_timeline_assets approved
                              WHERE approved.workspace_id = $2
                                AND approved.asset_id = deletion.asset_id
                          )
                    )""",
                    asset_id, workspace_id, claim_token,
                )
                if not claim_is_valid:
                    await connection.execute(
                        """DELETE FROM creator_media_asset_deletion_claims
                            WHERE asset_id = $1 AND workspace_id = $2 AND claim_token = $3
                              AND object_deleting = false""",
                        asset_id, workspace_id, claim_token,
                    )
                    return False
                await connection.execute(
                    """UPDATE creator_media_asset_deletion_claims
                        SET object_deleting = true
                        WHERE asset_id = $1 AND workspace_id = $2 AND claim_token = $3""",
                    asset_id, workspace_id, claim_token,
                )
            await delete_object()
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                result = await connection.execute(
                    """DELETE FROM creator_media_assets asset
                        WHERE asset.id = $1 AND asset.workspace_id = $2
                          AND EXISTS (
                            SELECT 1 FROM creator_media_asset_deletion_claims deletion
                            WHERE deletion.asset_id = asset.id
                              AND deletion.claim_token = $3
                              AND deletion.object_deleting = true
                          )""",
                    asset_id, workspace_id, claim_token,
                )
        return result == "DELETE 1"

    async def release_retained_asset(
        self, asset_id: int, workspace_id: int, claim_token: str,
    ) -> None:
        await db.execute(
            """DELETE FROM creator_media_asset_deletion_claims
                WHERE asset_id = $1 AND workspace_id = $2 AND claim_token = $3
                  AND object_deleting = false""",
            asset_id, workspace_id, claim_token,
        )
