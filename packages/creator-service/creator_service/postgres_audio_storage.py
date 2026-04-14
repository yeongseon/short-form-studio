from __future__ import annotations

import json
from typing import Any

from .db import fetch_all, fetch_one


class PostgresAudioStorage:
    async def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        metadata_json = row.get("metadata_json")
        if isinstance(metadata_json, dict):
            metadata_payload: str | None = json.dumps(metadata_json)
        else:
            metadata_payload = metadata_json

        saved = await fetch_one(
            """
            INSERT INTO creator_artifacts (
                run_id,
                artifact_type,
                scene_id,
                file_path,
                file_size_bytes,
                mime_type,
                metadata_json
            )
            VALUES ($1, 'audio', $2, $3, $4, $5, $6)
            RETURNING *
            """,
            row.get("run_id"),
            row.get("scene_id"),
            row.get("file_path"),
            row.get("file_size_bytes"),
            row.get("mime_type"),
            metadata_payload,
        )
        if saved is None:
            raise ValueError("Failed to save audio artifact")
        return saved

    async def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM creator_artifacts WHERE id = $1 AND artifact_type = 'audio'",
            artifact_id,
        )

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM creator_artifacts
            WHERE run_id = $1 AND artifact_type = 'audio' AND scene_id IS NULL
            ORDER BY created_at DESC
            """,
            run_id,
        )

    async def get_latest_by_run(self, run_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            """
            SELECT *
            FROM creator_artifacts
            WHERE run_id = $1 AND artifact_type = 'audio' AND scene_id IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
        )

    async def get_by_section(self, run_id: int, section_id: str) -> dict[str, Any] | None:
        return await fetch_one(
            """
            SELECT *
            FROM creator_artifacts
            WHERE run_id = $1 AND scene_id = $2 AND artifact_type = 'audio'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
            section_id,
        )

    async def list_by_run_sections(self, run_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM creator_artifacts
            WHERE run_id = $1 AND scene_id IS NOT NULL AND artifact_type = 'audio'
            ORDER BY scene_id, created_at DESC
            """,
            run_id,
        )

    async def delete_by_section(self, run_id: int, section_id: str) -> None:
        await fetch_one(
            """
            DELETE FROM creator_artifacts
            WHERE run_id = $1 AND scene_id = $2 AND artifact_type = 'audio'
            RETURNING id
            """,
            run_id,
            section_id,
        )
