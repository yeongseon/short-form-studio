from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one, get_pool


class PostgresVisualAssetStorage:
    async def save_asset(self, row: dict[str, Any]) -> dict[str, Any]:
        run_id = row["run_id"]
        scene_id = row["scene_id"]
        is_active = bool(row.get("is_active", False))

        pool = await get_pool()
        async with pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock($1::int, hashtext($2))",
                    run_id,
                    scene_id,
                )
                version_row = await connection.fetchrow(
                    """
                    SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                    FROM creator_scene_assets
                    WHERE run_id = $1 AND scene_id = $2
                    """,
                    run_id,
                    scene_id,
                )
                next_version = int(version_row["next_version"]) if version_row is not None else 1

                if is_active:
                    await connection.execute(
                        """
                        UPDATE creator_scene_assets
                        SET is_active = false
                        WHERE run_id = $1 AND scene_id = $2 AND is_active = true
                        """,
                        run_id,
                        scene_id,
                    )

                saved = await connection.fetchrow(
                    """
                    INSERT INTO creator_scene_assets (
                        run_id,
                        scene_id,
                        version,
                        asset_path,
                        prompt_snapshot,
                        model_used,
                        provider,
                        is_active
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING *
                    """,
                    run_id,
                    scene_id,
                    next_version,
                    row.get("asset_path"),
                    row.get("prompt_snapshot"),
                    row.get("model_used"),
                    row.get("provider"),
                    is_active,
                )
        if saved is None:
            raise ValueError("Failed to save visual asset")
        return dict(saved)

    async def get_asset(self, asset_id: int) -> dict[str, Any] | None:
        return await fetch_one("SELECT * FROM creator_scene_assets WHERE id = $1", asset_id)

    async def list_assets_by_scene(self, run_id: int, scene_id: str) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM creator_scene_assets
            WHERE run_id = $1 AND scene_id = $2
            ORDER BY version DESC
            """,
            run_id,
            scene_id,
        )

    async def list_assets_by_run(self, run_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM creator_scene_assets
            WHERE run_id = $1
            ORDER BY scene_id ASC, version DESC
            """,
            run_id,
        )

    async def set_active(self, run_id: int, scene_id: str, asset_id: int) -> bool:
        pool = await get_pool()
        async with pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock($1::int, hashtext($2))",
                    run_id,
                    scene_id,
                )
                await connection.execute(
                    """
                    UPDATE creator_scene_assets
                    SET is_active = false
                    WHERE run_id = $1 AND scene_id = $2
                    """,
                    run_id,
                    scene_id,
                )
                target = await connection.fetchrow(
                    """
                    UPDATE creator_scene_assets
                    SET is_active = true
                    WHERE run_id = $1 AND scene_id = $2 AND id = $3
                    RETURNING id
                    """,
                    run_id,
                    scene_id,
                    asset_id,
                )
        return target is not None

    async def get_active_asset(self, run_id: int, scene_id: str) -> dict[str, Any] | None:
        return await fetch_one(
            """
            SELECT *
            FROM creator_scene_assets
            WHERE run_id = $1 AND scene_id = $2 AND is_active = true
            LIMIT 1
            """,
            run_id,
            scene_id,
        )
