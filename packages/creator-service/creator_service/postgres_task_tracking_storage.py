from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .postgres_run_storage import PostgresRunStorage

from . import db
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
                error_message, claim_token
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
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
                END,
                claim_token = CASE WHEN EXCLUDED.status = 'running' THEN EXCLUDED.claim_token
                                   WHEN EXCLUDED.status = 'queued' THEN NULL
                                   ELSE creator_run_tasks.claim_token END
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
            row.get("claim_token"),
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


    async def update_task_status_if_running(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Atomically transition only if current status is running."""
        updated = await fetch_one(
            """
            UPDATE creator_run_tasks
            SET status = $2,
                started_at = COALESCE($3, started_at),
                finished_at = COALESCE($4, finished_at),
                error_code = $5,
                error_message = $6
            WHERE id = $1 AND status = 'running'
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
                error_message = NULL, claim_token = $3
            WHERE id = $1 AND status IN ('pending', 'queued', 'failed')
            RETURNING *
            """,
            task_id,
            kwargs.get("started_at"),
            kwargs.get("claim_token"),
        )
        return claimed

    async def finish_if_claimed(
        self, celery_task_id: str, token: str, status: str,
        error_code: str | None = None, error_message: str | None = None,
    ) -> dict[str, Any] | None:
        return await fetch_one(
            """UPDATE creator_run_tasks SET status=$3, claim_token=NULL, finished_at=NOW(),
               error_code=$4, error_message=$5
               WHERE celery_task_id=$1 AND claim_token=$2 AND status='running' RETURNING *""",
            celery_task_id, token, status, error_code, error_message,
        )

    async def finish_claimed_run(
        self, celery_task_id: str, token: str, status: str, run_storage: PostgresRunStorage,
        run_id: int, run_updates: dict[str, str], expected_stages: frozenset[str],
        rejected_statuses: frozenset[str], error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                claimed = await connection.fetchrow(
                    """SELECT id FROM creator_run_tasks WHERE celery_task_id=$1
                       AND claim_token=$2 AND status='running' AND run_id=$3 FOR UPDATE""",
                    celery_task_id, token, run_id,
                )
                if claimed is None:
                    return False
                await connection.fetchrow(
                    """UPDATE creator_runs SET current_stage=$2, status=$3, version=version+1
                       WHERE id=$1 AND current_stage=ANY($4::text[])
                       AND status != ALL($5::text[]) RETURNING id""",
                    run_id, run_updates["current_stage"], run_updates["status"],
                    list(expected_stages), list(rejected_statuses),
                )
                await connection.fetchrow(
                    """UPDATE creator_run_tasks SET status=$2, claim_token=NULL,
                       finished_at=NOW(), error_code=$3, error_message=$4
                       WHERE id=$1 RETURNING id""",
                    claimed["id"], status, error_code, error_message,
                )
                return True

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


    async def list_stale_pending_tasks(self, threshold_seconds: int) -> list[dict[str, Any]]:
        """Find tasks stuck in 'pending' state longer than threshold_seconds."""
        return await fetch_all(
            """
            SELECT *
            FROM creator_run_tasks
            WHERE status = 'pending'
              AND created_at < (NOW() - make_interval(secs => $1))
            ORDER BY created_at ASC
            """,
            threshold_seconds,
        )

    async def promote_pending_to_queued(self, celery_task_id: str) -> dict[str, Any] | None:
        """Atomically promote a task from 'pending' to 'queued'.

        Uses WHERE status = 'pending' to prevent clobbering a concurrent claim_running.
        """
        return await fetch_one(
            """
            UPDATE creator_run_tasks
            SET status = 'queued'
            WHERE celery_task_id = $1 AND status = 'pending'
            RETURNING *
            """,
            celery_task_id,
        )

    async def get_active_celery_ids(self, run_id: int) -> list[str]:
        rows = await fetch_all(
            "SELECT celery_task_id FROM creator_run_tasks "
            "WHERE run_id = $1 AND status IN ('queued', 'pending', 'running')",
            run_id,
        )
        return [row["celery_task_id"] for row in rows]
