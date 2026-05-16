from __future__ import annotations

import json
from typing import Any

from .db import fetch_all, fetch_one


class PostgresRenderStorage:
    async def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        idempotency_key = row.get("idempotency_key")
        if isinstance(idempotency_key, str):
            existing = await fetch_one(
                "SELECT * FROM creator_artifacts WHERE idempotency_key = $1",
                idempotency_key,
            )
            if existing is not None:
                return existing

        metadata_json = row.get("metadata_json")
        metadata_dict = metadata_json if isinstance(metadata_json, dict) else {}
        if isinstance(metadata_json, dict):
            metadata_payload: str | None = json.dumps(metadata_json)
        else:
            metadata_payload = metadata_json

        storage_backend = (
            row.get("storage_backend")
            or row.get("storage_provider")
            or metadata_dict.get("storage_backend")
            or metadata_dict.get("storage_provider")
        )
        storage_key = row.get("storage_key") or metadata_dict.get("storage_key")
        content_type = (
            row.get("content_type") or row.get("mime_type") or metadata_dict.get("content_type")
        )
        size_bytes = (
            row.get("size_bytes") or row.get("file_size_bytes") or metadata_dict.get("size_bytes")
        )

        saved = await fetch_one(
            """
            INSERT INTO creator_artifacts (
                run_id,
                artifact_type,
                scene_id,
                file_path,
                file_size_bytes,
                mime_type,
                metadata_json,
                idempotency_key,
                storage_backend,
                storage_key,
                content_type,
                size_bytes
            )
            VALUES ($1, 'video', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING *
            """,
            row.get("run_id"),
            row.get("scene_id"),
            row.get("file_path"),
            row.get("file_size_bytes"),
            row.get("mime_type"),
            metadata_payload,
            idempotency_key,
            storage_backend,
            storage_key,
            content_type,
            size_bytes,
        )
        if saved is None and isinstance(idempotency_key, str):
            existing = await fetch_one(
                "SELECT * FROM creator_artifacts WHERE idempotency_key = $1",
                idempotency_key,
            )
            if existing is not None:
                return existing
        if saved is None:
            raise ValueError("Failed to save render artifact")
        return saved

    async def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM creator_artifacts WHERE id = $1 AND artifact_type = 'video'",
            artifact_id,
        )

    async def list_by_run(
        self, run_id: int, workspace_id: int | None = None
    ) -> list[dict[str, Any]]:
        if workspace_id is None:
            return await fetch_all(
                """
                SELECT *
                FROM creator_artifacts
                WHERE run_id = $1 AND artifact_type = 'video'
                ORDER BY created_at DESC
                """,
                run_id,
            )
        return await fetch_all(
            """
            SELECT a.*
            FROM creator_artifacts a
            WHERE a.run_id = $1
              AND a.artifact_type = 'video'
              AND EXISTS (
                SELECT 1
                FROM creator_runs r
                WHERE r.id = a.run_id AND r.workspace_id = $2
              )
            ORDER BY a.created_at DESC
            """,
            run_id,
            workspace_id,
        )

    async def get_artifacts_for_run(
        self, run_id: int, workspace_id: int | None = None
    ) -> list[dict[str, Any]]:
        return await self.list_by_run(run_id, workspace_id=workspace_id)

    async def get_latest_by_run(self, run_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            """
            SELECT *
            FROM creator_artifacts
            WHERE run_id = $1 AND artifact_type = 'video'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            run_id,
        )
