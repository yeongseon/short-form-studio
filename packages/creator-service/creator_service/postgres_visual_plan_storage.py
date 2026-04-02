from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one, get_pool


class PostgresVisualPlanStorage:
    async def save_plan(self, row: dict[str, Any]) -> dict[str, Any]:
        run_id = row["run_id"]
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock($1::int, $2::int)",
                    6102,
                    run_id,
                )
                await connection.fetch(
                    "SELECT id FROM creator_visual_plans WHERE run_id = $1 FOR UPDATE",
                    run_id,
                )
                version_row = await connection.fetchrow(
                    "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM creator_visual_plans WHERE run_id = $1",
                    run_id,
                )
                next_version = int(version_row["next_version"]) if version_row is not None else 1
                saved = await connection.fetchrow(
                    """
                    INSERT INTO creator_visual_plans (
                        run_id,
                        scenes_json,
                        version
                    )
                    VALUES ($1, $2, $3)
                    RETURNING *
                    """,
                    run_id,
                    row.get("scenes_json"),
                    next_version,
                )
        if saved is None:
            raise ValueError("Failed to save visual plan")
        return dict(saved)

    async def get_active_plan(self, run_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            """
            SELECT *
            FROM creator_visual_plans
            WHERE run_id = $1
            ORDER BY version DESC
            LIMIT 1
            """,
            run_id,
        )

    async def list_plan_versions(self, run_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM creator_visual_plans
            WHERE run_id = $1
            ORDER BY version DESC
            """,
            run_id,
        )

    async def save_plan_if_version(
        self,
        row: dict[str, Any],
        expected_version: int,
    ) -> tuple[bool, dict[str, Any] | None, int | None]:
        run_id = row["run_id"]
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock($1::int, $2::int)",
                    6102,
                    run_id,
                )
                current = await connection.fetchrow(
                    """
                    SELECT *
                    FROM creator_visual_plans
                    WHERE run_id = $1
                    ORDER BY version DESC
                    LIMIT 1
                    FOR UPDATE
                    """,
                    run_id,
                )
                actual_version = int(current["version"]) if current is not None else 0
                if actual_version != expected_version:
                    return False, dict(current) if current is not None else None, actual_version

                saved = await connection.fetchrow(
                    """
                    INSERT INTO creator_visual_plans (
                        run_id,
                        scenes_json,
                        version
                    )
                    VALUES ($1, $2, $3)
                    RETURNING *
                    """,
                    run_id,
                    row.get("scenes_json"),
                    actual_version + 1,
                )
        if saved is None:
            raise ValueError("Failed to save visual plan")
        return True, dict(saved), expected_version
