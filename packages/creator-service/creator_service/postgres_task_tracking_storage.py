from __future__ import annotations

from typing import TYPE_CHECKING, Any, assert_never

if TYPE_CHECKING:
    from .postgres_run_storage import PostgresRunStorage

from .postgres_usage_storage import (
    cancel_owned_on_connection,
    finalize_revoked_owned_on_connection,
    settle_owned_on_connection,
)
from .task_tracking_storage import BillingOutcome

from . import db
from .db import fetch_all, fetch_one
from .run_update_columns import UPDATABLE_RUN_COLUMNS


class PostgresTaskTrackingStorage:
    async def _insert_pending_task(self, connection: Any, row: dict[str, Any]) -> dict[str, Any] | None:
        saved = await connection.fetchrow(
            """INSERT INTO creator_run_tasks
               (run_id, task_type, celery_task_id, status, attempt, broker_generation)
               VALUES ($1, $2, $3, 'pending', $4, $5)
               ON CONFLICT (celery_task_id) DO NOTHING RETURNING *""",
            row.get("run_id"), row.get("task_type"), row.get("celery_task_id"),
            row.get("attempt", 1),
            row.get("broker_generation"),
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
                error_message, claim_token, broker_generation
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
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
                                   ELSE creator_run_tasks.claim_token END,
                broker_generation = COALESCE(
                    EXCLUDED.broker_generation, creator_run_tasks.broker_generation
                )
            WHERE creator_run_tasks.status NOT IN ('success', 'running')
              AND (
                  creator_run_tasks.error_code IS NULL
                   OR NOT (creator_run_tasks.error_code = ANY($12::text[]))
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
            row.get("broker_generation"),
            [
                "reconciler_pending_cleanup",
                "reconciler_stuck_cleanup",
                "reconciler_cleanup_claimed",
                "broker_recovery_cleanup",
                "broker_message_lost",
            ],
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

    async def update_task_status_if_active(
        self, celery_task_id: str, status: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        return await fetch_one(
            """UPDATE creator_run_tasks SET status=$2, claim_token=NULL,
               finished_at=$3, error_code=$4, error_message=$5
               WHERE celery_task_id=$1 AND status IN ('pending', 'queued', 'running')
               RETURNING *""",
            celery_task_id,
            status,
            kwargs.get("finished_at"),
            kwargs.get("error_code"),
            kwargs.get("error_message"),
        )

    async def claim_running(self, task_id: int, **kwargs: Any) -> dict[str, Any] | None:
        """Lock and claim an eligible task after rechecking its observed owner."""
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                observed = await connection.fetchrow(
                    "SELECT status, claim_token, error_code FROM creator_run_tasks "
                    "WHERE id = $1 FOR UPDATE",
                    task_id,
                )
                if observed is None:
                    return None
                if observed["claim_token"] != kwargs.get("expected_claim_token"):
                    return None
                if observed["status"] not in {"pending", "queued", "failed"}:
                    return None
                if observed["error_code"] in {
                    "reconciler_pending_cleanup",
                    "reconciler_stuck_cleanup",
                    "reconciler_cleanup_claimed",
                    "broker_recovery_cleanup",
                    "broker_message_lost",
                }:
                    return None
                claimed = await connection.fetchrow(
                    """UPDATE creator_run_tasks SET status='running', started_at=$2,
                       finished_at=NULL, error_code=NULL, error_message=NULL, claim_token=$3
                       WHERE id=$1 RETURNING *""",
                    task_id, kwargs.get("started_at"), kwargs.get("claim_token"),
                )
                return dict(claimed) if claimed is not None else None

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
                run_updated = await connection.fetchrow(
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
                return run_updated is not None

    async def fail_claimed_and_cancel_quota(
        self, celery_task_id: str, token: str, usage_storage: Any,
        error_code: str, error_message: str, run_storage: PostgresRunStorage | None = None,
        run_id: int | None = None, expected_stages: frozenset[str] = frozenset(),
        billing_outcome: BillingOutcome | None = None,
    ) -> bool:
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                claimed = await connection.fetchrow(
                    """SELECT id, run_id FROM creator_run_tasks WHERE celery_task_id=$1
                       AND claim_token=$2 AND status='running' FOR UPDATE""",
                    celery_task_id, token,
                )
                if claimed is None:
                    return False
                if run_id is not None and int(claimed["run_id"]) == run_id:
                    await connection.execute(
                        """UPDATE creator_runs SET current_stage='FAILED', status='failed',
                           version=version+1 WHERE id=$1 AND current_stage=ANY($2::text[])
                           AND status != ALL($3::text[])""",
                        run_id, list(expected_stages), ["failed", "cancelled", "completed"],
                    )
                match billing_outcome:
                    case None:
                        await finalize_revoked_owned_on_connection(
                            connection, celery_task_id,
                        )
                    case BillingOutcome.NOT_STARTED:
                        await cancel_owned_on_connection(connection, celery_task_id)
                    case BillingOutcome.ACCOUNTED:
                        await settle_owned_on_connection(connection, celery_task_id)
                    case BillingOutcome.UNKNOWN:
                        await settle_owned_on_connection(
                            connection, celery_task_id, billable_unknown=True,
                        )
                    case unreachable:
                        assert_never(unreachable)
                await connection.execute(
                    """UPDATE creator_run_tasks SET status='failed', claim_token=NULL,
                       finished_at=NOW(), error_code=$2, error_message=$3 WHERE id=$1""",
                    claimed["id"], error_code, error_message,
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
                        'reconciler_pending_cleanup', 'reconciler_stuck_cleanup',
                        'broker_recovery_cleanup'
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
                    error_code IN (
                        'reconciler_pending_cleanup', 'reconciler_stuck_cleanup',
                        'broker_recovery_cleanup'
                    )
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
                  AND error_message IN (
                      'reconciler_pending_cleanup', 'reconciler_stuck_cleanup',
                      'broker_recovery_cleanup'
                  )
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

    async def list_broker_recovery_tasks(self) -> list[dict[str, Any]]:
        return await fetch_all(
            """SELECT * FROM creator_run_tasks
               WHERE status IN ('pending', 'queued', 'running')
               ORDER BY created_at ASC"""
        )

    async def get_observed_broker_epoch(self) -> str | None:
        row = await fetch_one(
            "SELECT epoch FROM creator_broker_state WHERE singleton = TRUE"
        )
        return str(row["epoch"]) if row is not None else None

    async def set_observed_broker_epoch(
        self, epoch: str, expected_previous_epoch: str | None
    ) -> bool:
        pool = await db.get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                inserted = await connection.fetchrow(
                    """INSERT INTO creator_broker_state (singleton, epoch, observed_at)
                       SELECT TRUE, $1, NOW() WHERE $2::text IS NULL
                       ON CONFLICT (singleton) DO NOTHING
                       RETURNING epoch""",
                    epoch,
                    expected_previous_epoch,
                )
                if inserted is not None:
                    await connection.execute(
                        """UPDATE creator_run_tasks SET broker_generation=$1
                           WHERE broker_generation IS NULL
                             AND status IN ('pending', 'queued', 'running')""",
                        epoch,
                    )
                    return True
                updated = await connection.fetchrow(
                    """UPDATE creator_broker_state
                       SET epoch=$1, observed_at=NOW()
                       WHERE singleton=TRUE
                         AND epoch IS NOT DISTINCT FROM $2
                       RETURNING epoch""",
                    epoch,
                    expected_previous_epoch,
                )
                if updated is not None and epoch != expected_previous_epoch:
                    await connection.execute(
                        """INSERT INTO creator_broker_cleanup_generations (generation)
                           VALUES ($1) ON CONFLICT (generation) DO NOTHING""",
                        expected_previous_epoch,
                    )
                return updated is not None

    async def list_pending_broker_cleanup_generations(self) -> list[str]:
        rows = await fetch_all(
            "SELECT generation FROM creator_broker_cleanup_generations ORDER BY generation"
        )
        return [str(row["generation"]) for row in rows]

    async def complete_broker_cleanup(self, generation: str) -> bool:
        removed = await fetch_one(
            """DELETE FROM creator_broker_cleanup_generations AS cleanup
               WHERE cleanup.generation=$1
                 AND NOT EXISTS (
                     SELECT 1 FROM creator_run_tasks AS tasks
                     WHERE tasks.broker_generation=cleanup.generation
                       AND tasks.status IN ('pending', 'queued', 'running')
                 )
               RETURNING generation""",
            generation,
        )
        return removed is not None

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
