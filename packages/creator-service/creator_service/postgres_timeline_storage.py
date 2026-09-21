"""SF-28: Postgres persistence for the one authoritative timeline per project.

The write is a single atomic statement that updates first (guarded by
``workspace_id`` + ``revision``) and inserts only on first save (when
``expected_revision == 0`` and no row was updated), so stale writes,
non-existent-then-nonzero-expected writes, and concurrent first-writes all
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
            updated AS (
                UPDATE creator_timelines
                SET timeline_id = $3,
                    segments_json = $4,
                    revision = revision + 1,
                    updated_at = now()
                WHERE project_id = $1
                  AND workspace_id = $2
                  AND revision = $5
                  AND EXISTS (SELECT 1 FROM authorized_project)
                RETURNING *
            ),
            inserted AS (
                INSERT INTO creator_timelines (
                    project_id, workspace_id, timeline_id, revision, segments_json
                )
                SELECT $1, $2, $3, 1, $4
                FROM authorized_project
                WHERE $5 = 0
                  AND NOT EXISTS (SELECT 1 FROM updated)
                ON CONFLICT (project_id) DO NOTHING
                RETURNING *
            )
            SELECT * FROM updated
            UNION ALL
            SELECT * FROM inserted
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
