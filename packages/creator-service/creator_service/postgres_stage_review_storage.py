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
                notes = json.loads(str(saved["notes"]))
                timeline_id = str(notes["timeline_id"])
                revision = int(notes["revision"])
                result = await connection.execute(
                    """INSERT INTO creator_approved_timeline_assets (
                        review_id, workspace_id, timeline_id, revision, asset_id
                    )
                    SELECT $1, r.workspace_id, $3, $4,
                        (segment->>'asset_id')::bigint
                    FROM creator_runs r
                    JOIN creator_timelines t ON t.project_id = r.project_id
                        AND t.workspace_id = r.workspace_id
                        AND t.timeline_id = $3 AND t.revision = $4
                    CROSS JOIN LATERAL jsonb_array_elements(t.segments_json::jsonb) segment
                    WHERE r.id = $2""",
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
