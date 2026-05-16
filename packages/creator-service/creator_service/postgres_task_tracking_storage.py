from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one


class PostgresTaskTrackingStorage:
    async def create_task(self, row: dict[str, Any]) -> dict[str, Any] | None:
        saved = await fetch_one(
            """
            INSERT INTO creator_run_tasks (
                run_id,
                task_type,
                celery_task_id,
                status,
                attempt,
                started_at,
                finished_at,
                error_code,
                error_message
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (celery_task_id) DO UPDATE
            SET status = EXCLUDED.status,
                attempt = CASE
                    WHEN EXCLUDED.status = 'queued' AND creator_run_tasks.status IN ('failed', 'running')
                        THEN creator_run_tasks.attempt + 1
                    ELSE creator_run_tasks.attempt
                END,
                started_at = CASE
                    WHEN EXCLUDED.status = 'running' THEN EXCLUDED.started_at
                    WHEN EXCLUDED.status = 'queued' THEN NULL
                    ELSE creator_run_tasks.started_at
                END,
                finished_at = CASE
                    WHEN EXCLUDED.status IN ('queued', 'running') THEN NULL
                    ELSE creator_run_tasks.finished_at
                END,
                error_code = CASE
                    WHEN EXCLUDED.status IN ('queued', 'running') THEN NULL
                    ELSE creator_run_tasks.error_code
                END,
                error_message = CASE
                    WHEN EXCLUDED.status IN ('queued', 'running') THEN NULL
                    ELSE creator_run_tasks.error_message
                END
            WHERE creator_run_tasks.status NOT IN ('success', 'running')
            RETURNING *
            """,
            row.get("run_id"),
            row.get("task_type"),
            row.get("celery_task_id"),
            row.get("status", "queued"),
            row.get("attempt", 1),
            row.get("started_at"),
            row.get("finished_at"),
            row.get("error_code"),
            row.get("error_message"),
        )
        return saved

    async def update_task_status(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        updated = await fetch_one(
            """
            UPDATE creator_run_tasks
            SET status = $2,
                started_at = COALESCE($3, started_at),
                finished_at = COALESCE($4, finished_at),
                error_code = $5,
                error_message = $6
            WHERE id = $1 AND status != 'success'
            RETURNING *
            """,
            task_id,
            status,
            kwargs.get("started_at"),
            kwargs.get("finished_at"),
            kwargs.get("error_code"),
            kwargs.get("error_message"),
        )
        return updated

    async def claim_running(self, task_id: int, **kwargs: Any) -> dict[str, Any] | None:
        """Atomically claim: only transition from queued/failed to running.

        Uses WHERE status IN ('queued', 'failed') so only one concurrent caller wins.
        """
        claimed = await fetch_one(
            """
            UPDATE creator_run_tasks
            SET status = 'running',
                started_at = $2,
                finished_at = NULL,
                error_code = NULL,
                error_message = NULL
            WHERE id = $1 AND status IN ('queued', 'failed')
            RETURNING *
            """,
            task_id,
            kwargs.get("started_at"),
        )
        return claimed

    async def get_by_celery_id(self, celery_task_id: str) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM creator_run_tasks WHERE celery_task_id = $1",
            celery_task_id,
        )

    async def list_by_run(self, run_id: int) -> list[dict[str, Any]]:
        return await fetch_all(
            "SELECT * FROM creator_run_tasks WHERE run_id = $1 ORDER BY id DESC",
            run_id,
        )

    async def list_stuck_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM creator_run_tasks
            WHERE status = 'running'
              AND started_at IS NOT NULL
              AND started_at < (NOW() - make_interval(secs => $1))
            ORDER BY started_at ASC
            """,
            threshold_seconds,
        )

    async def get_active_celery_ids(self, run_id: int) -> list[str]:
        rows = await fetch_all(
            "SELECT celery_task_id FROM creator_run_tasks "
            "WHERE run_id = $1 AND status IN ('queued', 'pending', 'running')",
            run_id,
        )
        return [row["celery_task_id"] for row in rows]
