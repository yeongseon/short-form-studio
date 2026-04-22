from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one, get_pool


class PostgresScriptStorage:
    async def save_draft(self, row: dict[str, Any]) -> dict[str, Any]:
        run_id = row["run_id"]
        pool = await get_pool()
        async with pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock($1::int, $2::int)",
                    6101,
                    run_id,
                )
                await connection.fetch(
                    "SELECT id FROM creator_script_drafts WHERE run_id = $1 FOR UPDATE",
                    run_id,
                )
                version_row = await connection.fetchrow(
                    "SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM creator_script_drafts WHERE run_id = $1",
                    run_id,
                )
                next_version = int(version_row["next_version"]) if version_row is not None else 1
                saved = await connection.fetchrow(
                    """
                    INSERT INTO creator_script_drafts (
                        run_id,
                        source_type,
                        markdown_content,
                        structured_script_json,
                        version
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING *
                    """,
                    run_id,
                    row.get("source_type"),
                    row.get("markdown_content"),
                    row.get("structured_script_json"),
                    next_version,
                )
        if saved is None:
            raise ValueError("Failed to save script draft")
        return dict(saved)

    async def get_active_draft(self, run_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            """
            SELECT *
            FROM creator_script_drafts
            WHERE run_id = $1
            ORDER BY version DESC
            LIMIT 1
            """,
            run_id,
        )

    async def list_draft_versions(self, run_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM creator_script_drafts
            WHERE run_id = $1
            ORDER BY version DESC
            """,
            run_id,
        )
