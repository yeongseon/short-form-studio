"""SF-28: Postgres persistence for the one authoritative timeline per project.

The write is a single atomic statement: it inserts on first save (only when
``expected_revision == 0``) or updates on conflict guarded by
``workspace_id`` + ``revision``, so stale writes and concurrent first-writes
return no row (the service maps that to a VersionConflictError).
"""

from __future__ import annotations

from typing import Any

from .db import fetch_one


class PostgresTimelineStorage:
    async def save_timeline(
        self,
        *,
        project_id: int,
        workspace_id: int,
        timeline_id: str,
        segments_json: str,
        expected_revision: int,
    ) -> dict[str, Any] | None:
        return await fetch_one(
            """
            WITH authorized_project AS (
                SELECT id FROM creator_projects
                WHERE id = $1 AND workspace_id = $2
            ),
            upserted AS (
                INSERT INTO creator_timelines (
                    project_id, workspace_id, timeline_id, revision, segments_json
                )
                SELECT $1, $2, $3, 1, $4
                FROM authorized_project
                WHERE $5 = 0
                ON CONFLICT (project_id) DO UPDATE
                SET timeline_id = EXCLUDED.timeline_id,
                    segments_json = EXCLUDED.segments_json,
                    revision = creator_timelines.revision + 1,
                    updated_at = now()
                WHERE creator_timelines.workspace_id = EXCLUDED.workspace_id
                  AND creator_timelines.revision = $5
                RETURNING *
            )
            SELECT * FROM upserted
            """,
            project_id,
            workspace_id,
            timeline_id,
            segments_json,
            expected_revision,
        )

    async def load_timeline(
        self, *, project_id: int, workspace_id: int
    ) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM creator_timelines WHERE project_id = $1 AND workspace_id = $2",
            project_id,
            workspace_id,
        )
