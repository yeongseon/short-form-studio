from __future__ import annotations

from datetime import datetime
from typing import Any

from .db import fetch_all, fetch_one


class PostgresUsageStorage:
    async def record_event(self, row: dict[str, Any]) -> dict[str, Any]:
        saved = await fetch_one(
            """
            INSERT INTO usage_events (
                workspace_id,
                project_id,
                run_id,
                provider,
                model_key,
                operation_type,
                input_tokens,
                output_tokens,
                image_count,
                audio_seconds,
                estimated_cost_usd
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
            """,
            row.get("workspace_id"),
            row.get("project_id"),
            row.get("run_id"),
            row.get("provider"),
            row.get("model_key"),
            row.get("operation_type"),
            row.get("input_tokens"),
            row.get("output_tokens"),
            row.get("image_count"),
            row.get("audio_seconds"),
            row.get("estimated_cost_usd"),
        )
        if saved is None:
            raise ValueError("Failed to create usage event")
        return saved

    async def list_by_workspace(self, workspace_id: int, since: datetime) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM usage_events
            WHERE workspace_id = $1 AND created_at >= $2
            ORDER BY created_at ASC, id ASC
            """,
            workspace_id,
            since,
        )

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM usage_events
            WHERE run_id = $1
            ORDER BY created_at ASC, id ASC
            """,
            run_id,
        )

    async def get_workspace_quota(self, workspace_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM workspace_quotas WHERE workspace_id = $1",
            workspace_id,
        )

    async def set_workspace_quota(self, workspace_id: int, quota: dict[str, Any]) -> dict[str, Any]:
        saved = await fetch_one(
            """
            INSERT INTO workspace_quotas (
                workspace_id,
                monthly_llm_calls,
                monthly_image_generations,
                monthly_tts_seconds,
                monthly_cost_usd
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (workspace_id)
            DO UPDATE SET
                monthly_llm_calls = EXCLUDED.monthly_llm_calls,
                monthly_image_generations = EXCLUDED.monthly_image_generations,
                monthly_tts_seconds = EXCLUDED.monthly_tts_seconds,
                monthly_cost_usd = EXCLUDED.monthly_cost_usd,
                updated_at = NOW()
            RETURNING *
            """,
            workspace_id,
            quota["monthly_llm_calls"],
            quota["monthly_image_generations"],
            quota["monthly_tts_seconds"],
            quota["monthly_cost_usd"],
        )
        if saved is None:
            raise ValueError(f"Failed to set quota for workspace {workspace_id}")
        return saved
