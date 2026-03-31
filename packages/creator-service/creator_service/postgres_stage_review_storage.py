from __future__ import annotations

from typing import Any

from .db import fetch_one


class PostgresStageReviewStorage:
    async def create_review(self, row: dict[str, Any]) -> dict[str, Any]:
        saved = await fetch_one(
            """
            INSERT INTO creator_stage_reviews (
                run_id,
                stage_name,
                review_status,
                reviewer,
                notes
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            row.get("run_id"),
            row.get("stage_name"),
            row.get("review_status"),
            row.get("reviewer"),
            row.get("notes"),
        )
        if saved is None:
            raise ValueError("Failed to create stage review")
        return saved

    async def get_latest_review(self, run_id: int, stage_name: str) -> dict[str, Any] | None:
        return await fetch_one(
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
