from __future__ import annotations

import json
from typing import Any

from . import db


class PostgresStageReviewStorage:
    async def create_review(self, row: dict[str, Any]) -> dict[str, Any]:
        pool = await db.get_pool()
        async with pool.acquire() as connection, connection.transaction():
            saved = await connection.fetchrow(
                """INSERT INTO creator_stage_reviews (
                    run_id, stage_name, review_status, reviewer, notes
                ) VALUES ($1, $2, $3, $4, $5) RETURNING *""",
                row.get("run_id"), row.get("stage_name"), row.get("review_status"),
                row.get("reviewer"), row.get("notes"),
            )
            if saved is None:
                raise ValueError("Failed to create stage review")
            if saved["stage_name"] == "TIMELINE_REVIEW" and saved["review_status"] == "approved":
                workspace_id = await connection.fetchval(
                    "SELECT workspace_id FROM creator_runs WHERE id = $1",
                    int(saved["run_id"]),
                )
                if workspace_id is None:
                    raise ValueError("Approved Timeline run not found")
                await connection.execute("SELECT pg_advisory_xact_lock($1)", int(workspace_id))
                notes = json.loads(str(saved["notes"]))
                timeline_id = str(notes["timeline_id"])
                revision = int(notes["revision"])
                result = await connection.execute(
                    """WITH exact_timeline AS (
                        SELECT r.workspace_id, t.segments_json
                        FROM creator_runs r
                        JOIN creator_timelines t ON t.project_id = r.project_id
                            AND t.workspace_id = r.workspace_id
                            AND t.timeline_id = $3 AND t.revision = $4
                        WHERE r.id = $2
                    ), mapped AS (
                        INSERT INTO creator_approved_timeline_assets (
                            review_id, workspace_id, timeline_id, revision, asset_id
                        )
                        SELECT DISTINCT $1::integer, exact.workspace_id, $3::text, $4::integer,
                            (segment->>'asset_id')::bigint
                        FROM exact_timeline exact
                        CROSS JOIN LATERAL jsonb_array_elements(exact.segments_json::jsonb) segment
                        WHERE NOT EXISTS (
                            SELECT 1 FROM creator_media_asset_deletion_claims deletion
                            WHERE deletion.asset_id = (segment->>'asset_id')::bigint
                              AND deletion.workspace_id = exact.workspace_id
                              AND deletion.lease_expires_at > now()
                        )
                        RETURNING review_id
                    )
                    INSERT INTO creator_resolved_timeline_approvals (review_id)
                    SELECT $1::integer FROM exact_timeline exact
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM jsonb_array_elements(exact.segments_json::jsonb) segment
                        JOIN creator_media_asset_deletion_claims deletion
                          ON deletion.asset_id = (segment->>'asset_id')::bigint
                         AND deletion.workspace_id = exact.workspace_id
                         AND deletion.lease_expires_at > now()
                    ) RETURNING review_id""",
                    int(saved["id"]), int(saved["run_id"]), timeline_id, revision,
                )
                if result == "INSERT 0 0":
                    raise ValueError("Approved Timeline revision not found")
        return dict(saved)

    async def get_latest_review(self, run_id: int, stage_name: str) -> dict[str, Any] | None:
        return await db.fetch_one(
            """
            SELECT *
            FROM creator_stage_reviews
            WHERE run_id = $1 AND stage_name = $2
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            run_id,
            stage_name,
        )
