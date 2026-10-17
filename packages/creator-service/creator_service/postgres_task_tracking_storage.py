from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .postgres_run_storage import PostgresRunStorage

from . import db
from .db import fetch_all, fetch_one
from .run_update_columns import UPDATABLE_RUN_COLUMNS


class PostgresTaskTrackingStorage:
    async def _insert_pending_task(self, connection: Any, row: dict[str, Any]) -> dict[str, Any] | None:
        saved = await connection.fetchrow(
            """INSERT INTO creator_run_tasks
               (run_id, task_type, celery_task_id, status, attempt)
               VALUES ($1, $2, $3, 'pending', $4)
               ON CONFLICT (celery_task_id) DO NOTHING RETURNING *""",
            row.get("run_id"), row.get("task_type"), row.get("celery_task_id"),
            row.get("attempt", 1),
        )
        return dict(saved) if saved is not None else None

    async def transition_run_and_create_pending(
        self, run_storage: PostgresRunStorage, run_id: int, updates: dict[str, Any],
        expected_stages: frozenset[str], task_row: dict[str, Any],
        workspace_id: int | None, rejected_statuses: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]:
        del run_storage
        invalid_columns = set(updates) - UPDATABLE_RUN_COLUMNS
        if invalid_columns:
            invalid_list = ", ".join(sorted(invalid_columns))
            raise ValueError(f"Invalid update columns: {invalid_list}")
        keys = list(updates)
        assignments = ", ".join(f"{key} = ${index}" for index, key in enumerate(keys, start=3))
        values = [run_id, list(expected_stages), *[updates[key] for key in keys]]
        clauses = ["id = $1", "current_stage = ANY($2::text[])"]
        clauses.append(f"status != ALL(${len(values) + 1}::text[])")
        values.append(list(rejected_statuses))
        if workspace_id is not None:
            clauses.append(f"workspace_id = ${len(values) + 1}")
            values.append(workspace_id)
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                updated = await connection.fetchrow(
                    f"UPDATE creator_runs SET {assignments}, version=version+1 "
                    f"WHERE {' AND '.join(clauses)} RETURNING *",
                    *values,
                )
                if updated is None:
                    current = await connection.fetchrow(
                        "SELECT * FROM creator_runs WHERE id=$1", run_id
                    )
                    return False, dict(current) if current is not None else None
                pending = await self._insert_pending_task(connection, task_row)
                if pending is None:
                    raise ValueError("Pending task ownership already exists")
                return True, dict(updated)

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
              AND (
                  creator_run_tasks.error_code IS NULL
                  OR NOT (creator_run_tasks.error_code = ANY($11::text[]))
              )
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
            ["reconciler_pending_cleanup", "reconciler_stuck_cleanup", "reconciler_cleanup_claimed"],
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

    async def update_task_status_if_pending(
        self, task_id: int, status: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        return await fetch_one(
            """UPDATE creator_run_tasks SET status=$2, finished_at=COALESCE($3, finished_at),
               error_code=$4, error_message=$5
               WHERE id=$1 AND status='pending' RETURNING *""",
            task_id,
            status,
            kwargs.get("finished_at"),
            kwargs.get("error_code"),
            kwargs.get("error_message"),
        )

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
              AND (error_code IS NULL OR NOT (error_code = ANY($4::text[])))
            RETURNING *
            """,
            task_id,
            kwargs.get("started_at"),
            kwargs.get("claim_token"),
            ["reconciler_pending_cleanup", "reconciler_stuck_cleanup", "reconciler_cleanup_claimed"],
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

    async def list_reconciliation_pending_tasks(
        self, lease_seconds: int
    ) -> list[dict[str, Any]]:
        return await fetch_all(
            """SELECT * FROM creator_run_tasks
               WHERE status='failed' AND (
                   error_code IN (
                       'reconciler_pending_cleanup', 'reconciler_stuck_cleanup'
                   ) OR (
                       error_code='reconciler_cleanup_claimed'
                       AND finished_at < NOW() - make_interval(secs => $1)
                   )
               ) ORDER BY finished_at ASC NULLS LAST""",
            lease_seconds,
        )

    async def claim_reconciliation(
        self, task_id: int, claim_token: str, lease_seconds: int
    ) -> dict[str, Any] | None:
        return await fetch_one(
            """UPDATE creator_run_tasks
               SET error_message=CASE
                       WHEN error_code='reconciler_cleanup_claimed' THEN error_message
                       ELSE error_code
                   END,
                   error_code='reconciler_cleanup_claimed',
                   claim_token=$2, finished_at=NOW()
               WHERE id=$1 AND status='failed' AND (
                   error_code IN ('reconciler_pending_cleanup', 'reconciler_stuck_cleanup')
                   OR (error_code='reconciler_cleanup_claimed'
                       AND finished_at < NOW() - make_interval(secs => $3))
               ) RETURNING *""",
            task_id, claim_token, lease_seconds,
        )

    async def finish_reconciliation(
        self, celery_task_id: str, claim_token: str, error_code: str, error_message: str
    ) -> dict[str, Any] | None:
        return await fetch_one(
            """UPDATE creator_run_tasks SET error_code=$3, error_message=$4, claim_token=NULL
               WHERE celery_task_id=$1 AND claim_token=$2
                 AND error_code='reconciler_cleanup_claimed' RETURNING *""",
            celery_task_id, claim_token, error_code, error_message,
        )

    async def release_reconciliation(
        self, celery_task_id: str, claim_token: str
    ) -> dict[str, Any] | None:
        return await fetch_one(
            """UPDATE creator_run_tasks
               SET error_code=error_message, error_message='Cleanup retry required', claim_token=NULL
               WHERE celery_task_id=$1 AND claim_token=$2
                 AND error_code='reconciler_cleanup_claimed'
                 AND error_message IN ('reconciler_pending_cleanup', 'reconciler_stuck_cleanup')
               RETURNING *""",
            celery_task_id, claim_token,
        )

    async def rollback_run_if_task_owner(
        self, celery_task_id: str, run_storage: PostgresRunStorage,
        run_id: int, eligible_task_types: frozenset[str],
        expected_stages: frozenset[str], rejected_statuses: frozenset[str],
    ) -> tuple[bool, dict[str, Any] | None]:
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                updated = await connection.fetchrow(
                    """UPDATE creator_runs AS runs
                       SET current_stage='FAILED', status='failed', version=version+1
                       FROM creator_run_tasks AS owner
                       WHERE runs.id=$1 AND owner.celery_task_id=$2
                         AND owner.run_id=runs.id AND owner.task_type=ANY($3::text[])
                         AND runs.current_stage=ANY($4::text[])
                         AND runs.status != ALL($5::text[])
                         AND NOT EXISTS (
                             SELECT 1 FROM creator_run_tasks AS newer
                             WHERE newer.run_id=owner.run_id
                               AND newer.task_type=owner.task_type AND newer.id>owner.id
                               AND newer.status IN ('pending','queued','running','success')
                         ) RETURNING runs.*""",
                    run_id, celery_task_id, list(eligible_task_types),
                    list(expected_stages), list(rejected_statuses),
                )
                if updated is not None:
                    return True, dict(updated)
                current = await connection.fetchrow("SELECT * FROM creator_runs WHERE id=$1", run_id)
                return False, dict(current) if current is not None else None

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
