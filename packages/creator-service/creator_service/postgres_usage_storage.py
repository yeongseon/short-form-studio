from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from .db import fetch_all, fetch_one, get_pool


class PostgresUsageStorage:
    async def record_event(self, row: dict[str, Any]) -> dict[str, Any]:
        idempotency_key = row.get("idempotency_key")
        workspace_id = row.get("workspace_id")
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                if isinstance(workspace_id, int):
                    await connection.execute(
                        "SELECT pg_advisory_xact_lock($1)", workspace_id
                    )
                saved = await connection.fetchrow(
                    """
            INSERT INTO usage_events (
                workspace_id,
                project_id,
                run_id,
                provider,
                model_key,
                operation_type,
                input_tokens,
                output_tokens,
                image_count,
                audio_seconds,
                estimated_cost_usd,
                cost_config_version,
                idempotency_key
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING *
            """,
                    workspace_id, row.get("project_id"), row.get("run_id"),
                    row.get("provider"), row.get("model_key"), row.get("operation_type"),
                    row.get("input_tokens"), row.get("output_tokens"), row.get("image_count"),
                    row.get("audio_seconds"), row.get("estimated_cost_usd"),
                    row.get("cost_config_version"), idempotency_key,
                )
                if saved is None and isinstance(idempotency_key, str):
                    saved = await connection.fetchrow(
                        "SELECT * FROM usage_events WHERE idempotency_key = $1",
                        idempotency_key,
                    )
                if saved is None:
                    raise ValueError("Failed to create usage event")
                return dict(saved)

    async def list_by_workspace(self, workspace_id: int, since: datetime) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM usage_events
            WHERE workspace_id = $1 AND created_at >= $2
            ORDER BY created_at ASC, id ASC
            """,
            workspace_id,
            since,
        )

    async def list_by_run(
        self, run_id: int, workspace_id: int | None = None
    ) -> list[dict[str, Any]]:
        if workspace_id is None:
            return await fetch_all(
                """
                SELECT *
                FROM usage_events
                WHERE run_id = $1
                ORDER BY created_at ASC, id ASC
                """,
                run_id,
            )
        return await fetch_all(
            """
            SELECT *
            FROM usage_events
            WHERE run_id = $1 AND workspace_id = $2
            ORDER BY created_at ASC, id ASC
            """,
            run_id,
            workspace_id,
        )

    async def get_workspace_quota(self, workspace_id: int) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM workspace_quotas WHERE workspace_id = $1",
            workspace_id,
        )

    async def set_workspace_quota(self, workspace_id: int, quota: dict[str, Any]) -> dict[str, Any]:
        saved = await fetch_one(
            """
            INSERT INTO workspace_quotas (
                workspace_id,
                monthly_llm_calls,
                monthly_image_generations,
                monthly_tts_requests,
                monthly_cost_usd
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (workspace_id)
            DO UPDATE SET
                monthly_llm_calls = EXCLUDED.monthly_llm_calls,
                monthly_image_generations = EXCLUDED.monthly_image_generations,
                monthly_tts_requests = EXCLUDED.monthly_tts_requests,
                monthly_cost_usd = EXCLUDED.monthly_cost_usd,
                updated_at = NOW()
            RETURNING *
            """,
            workspace_id,
            quota["monthly_llm_calls"],
            quota["monthly_image_generations"],
            quota["monthly_tts_requests"],
            quota["monthly_cost_usd"],
        )
        if saved is None:
            raise ValueError(f"Failed to set quota for workspace {workspace_id}")
        return saved

    async def try_reserve_quota(
        self, workspace_id: int, operation_type: str, owner_id: str | None = None,
    ) -> bool:
        if operation_type not in {"llm", "image_gen", "tts", "stt", "render"}:
            return True

        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                if owner_id is not None:
                    existing = await connection.fetchrow(
                        "SELECT workspace_id, operation_type, status FROM workspace_quota_reservation_owners WHERE owner_id = $1",
                        owner_id,
                    )
                    if existing is not None:
                        return (
                            existing["workspace_id"] == workspace_id
                            and existing["operation_type"] == operation_type
                            and existing["status"] == "reserved"
                        )
                quota = await connection.fetchrow(
                    "SELECT * FROM workspace_quotas WHERE workspace_id = $1",
                    workspace_id,
                )
                if quota is None:
                    quota = await connection.fetchrow(
                        """
                        INSERT INTO workspace_quotas (
                            workspace_id,
                            monthly_llm_calls,
                            monthly_image_generations,
                            monthly_tts_requests,
                            monthly_cost_usd
                        )
                        VALUES ($1, 1000, 200, 3600, 50.00)
                        ON CONFLICT (workspace_id) DO UPDATE
                        SET updated_at = NOW()
                        RETURNING *
                        """,
                        workspace_id,
                    )

                month_start = await connection.fetchval(
                    "SELECT date_trunc('month', NOW() AT TIME ZONE 'UTC')::timestamptz"
                )
                assert month_start is not None

                usage_row = await connection.fetchrow(
                    """
                    SELECT
                        COALESCE(SUM(CASE WHEN operation_type = 'llm' THEN 1 ELSE 0 END), 0)::integer AS llm_count,
                        COALESCE(
                            SUM(
                                CASE
                                    WHEN operation_type = 'image_gen'
                                        THEN CASE WHEN COALESCE(image_count, 0) > 0 THEN image_count ELSE 1 END
                                    ELSE 0
                                END
                            ),
                            0
                        )::integer AS image_count,
                        COALESCE(
                            SUM(CASE WHEN operation_type IN ('tts', 'stt', 'render') THEN 1 ELSE 0 END),
                            0
                        )::integer AS tts_request_count
                    FROM usage_events
                    WHERE workspace_id = $1 AND created_at >= $2
                    """,
                    workspace_id,
                    month_start,
                )
                if usage_row is None:
                    return False

                reservation_row = await connection.fetchrow(
                    """
                    SELECT llm_count, image_count, tts_request_count
                    FROM workspace_quota_reservations
                    WHERE workspace_id = $1 AND period_start = $2
                    """,
                    workspace_id,
                    month_start,
                )
                reserved_llm = int(reservation_row["llm_count"]) if reservation_row else 0
                reserved_image = int(reservation_row["image_count"]) if reservation_row else 0
                reserved_tts = int(reservation_row["tts_request_count"]) if reservation_row else 0

                allowed = True
                if operation_type == "llm":
                    allowed = int(usage_row["llm_count"]) + reserved_llm < int(
                        quota["monthly_llm_calls"]
                    )
                elif operation_type == "image_gen":
                    allowed = int(usage_row["image_count"]) + reserved_image < int(
                        quota["monthly_image_generations"]
                    )
                elif operation_type in {"tts", "stt", "render"}:
                    allowed = int(usage_row["tts_request_count"]) + reserved_tts < int(
                        quota["monthly_tts_requests"]
                    )

                if not allowed:
                    return False

                llm_increment = 1 if operation_type == "llm" else 0
                image_increment = 1 if operation_type == "image_gen" else 0
                tts_increment = 1 if operation_type in {"tts", "stt", "render"} else 0
                await connection.execute(
                    """
                    INSERT INTO workspace_quota_reservations (
                        workspace_id,
                        period_start,
                        llm_count,
                        image_count,
                        tts_request_count
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (workspace_id, period_start)
                    DO UPDATE SET
                        llm_count = workspace_quota_reservations.llm_count + EXCLUDED.llm_count,
                        image_count = workspace_quota_reservations.image_count + EXCLUDED.image_count,
                        tts_request_count = workspace_quota_reservations.tts_request_count + EXCLUDED.tts_request_count,
                        updated_at = NOW()
                    """,
                    workspace_id,
                    month_start,
                    llm_increment,
                    image_increment,
                    tts_increment,
                )
                if owner_id is not None:
                    await connection.execute(
                        """INSERT INTO workspace_quota_reservation_owners
                           (owner_id, workspace_id, period_start, operation_type, status)
                           VALUES ($1, $2, $3, $4, 'reserved')""",
                        owner_id, workspace_id, month_start, operation_type,
                    )
                return True

    async def try_reserve_owned(
        self, workspace_id: int, operation_type: str, owner_id: str,
        estimated_cost_usd: Decimal, monthly_cost_usd: Decimal,
        global_monthly_cost_usd: Decimal | None,
    ) -> bool:
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                if global_monthly_cost_usd is not None:
                    await connection.execute("SELECT pg_advisory_xact_lock($1)", 860)
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                month_start = await connection.fetchval(
                    "SELECT date_trunc('month', NOW() AT TIME ZONE 'UTC')::timestamptz"
                )
                existing = await connection.fetchrow(
                    """SELECT workspace_id, operation_type, status, period_start
                       FROM workspace_quota_reservation_owners
                       WHERE owner_id = $1""",
                    owner_id,
                )
                if existing is not None:
                    return (
                        existing["workspace_id"] == workspace_id
                        and existing["operation_type"] == operation_type
                        and existing["period_start"] == month_start
                        and existing["status"] in {"reserved", "consumed"}
                    )
                settled_workspace = await connection.fetchval(
                    """SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM usage_events
                       WHERE workspace_id = $1 AND created_at >= $2""",
                    workspace_id, month_start,
                )
                reserved_workspace = await connection.fetchval(
                    """SELECT COALESCE(SUM(GREATEST(
                         estimated_cost_usd - settled_estimated_cost_usd, 0)), 0)
                       FROM workspace_quota_reservation_owners
                       WHERE workspace_id = $1 AND period_start = $2
                         AND status IN ('reserved', 'consumed', 'billable_unknown')""",
                    workspace_id, month_start,
                )
                if settled_workspace + reserved_workspace + estimated_cost_usd > monthly_cost_usd:
                    return False
                if global_monthly_cost_usd is not None:
                    global_accounting = await connection.fetchrow(
                        """SELECT
                           (SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM usage_events
                            WHERE created_at >= $1) AS settled,
                           (SELECT COALESCE(SUM(GREATEST(
                              estimated_cost_usd - settled_estimated_cost_usd, 0)), 0)
                            FROM workspace_quota_reservation_owners
                            WHERE period_start = $1
                              AND status IN ('reserved', 'consumed', 'billable_unknown')) AS reserved""",
                        month_start,
                    )
                    if (
                        global_accounting["settled"]
                        + global_accounting["reserved"]
                        + estimated_cost_usd
                        > global_monthly_cost_usd
                    ):
                        return False
                allowed = await self._reserve_count(
                    connection, workspace_id, operation_type, owner_id, month_start,
                    estimated_cost_usd,
                )
                return allowed

    async def _reserve_count(
        self, connection: Any, workspace_id: int, operation_type: str, owner_id: str,
        month_start: datetime, estimated_cost_usd: Decimal,
    ) -> bool:
        quota = await connection.fetchrow(
            "SELECT * FROM workspace_quotas WHERE workspace_id = $1", workspace_id,
        )
        if quota is None:
            quota = await connection.fetchrow(
                """INSERT INTO workspace_quotas
                   (workspace_id, monthly_llm_calls, monthly_image_generations,
                    monthly_tts_requests, monthly_cost_usd)
                   VALUES ($1, 1000, 200, 3600, 50.00) RETURNING *""",
                workspace_id,
            )
        usage = await connection.fetchrow(
            """SELECT
               COALESCE(SUM((operation_type = 'llm')::int), 0)::int AS llm_count,
               COALESCE(SUM(CASE WHEN operation_type = 'image_gen'
                 THEN GREATEST(COALESCE(image_count, 0), 1) ELSE 0 END), 0)::int AS image_count,
               COALESCE(SUM((operation_type IN ('tts','stt','render'))::int), 0)::int AS tts_count
               FROM usage_events WHERE workspace_id = $1 AND created_at >= $2""",
            workspace_id, month_start,
        )
        reserved = await connection.fetchrow(
            """SELECT llm_count, image_count, tts_request_count
               FROM workspace_quota_reservations WHERE workspace_id = $1 AND period_start = $2""",
            workspace_id, month_start,
        )
        llm_count = int(usage["llm_count"]) + (int(reserved["llm_count"]) if reserved else 0)
        image_count = int(usage["image_count"]) + (int(reserved["image_count"]) if reserved else 0)
        tts_count = int(usage["tts_count"]) + (int(reserved["tts_request_count"]) if reserved else 0)
        if operation_type == "llm" and llm_count >= int(quota["monthly_llm_calls"]):
            return False
        if operation_type == "image_gen" and image_count >= int(quota["monthly_image_generations"]):
            return False
        if operation_type in {"tts", "stt", "render"} and tts_count >= int(quota["monthly_tts_requests"]):
            return False
        increments = (
            int(operation_type == "llm"), int(operation_type == "image_gen"),
            int(operation_type in {"tts", "stt", "render"}),
        )
        await connection.execute(
            """INSERT INTO workspace_quota_reservations
               (workspace_id, period_start, llm_count, image_count, tts_request_count,
                reserved_estimated_cost_usd)
               VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (workspace_id, period_start) DO UPDATE SET
                 llm_count = workspace_quota_reservations.llm_count + EXCLUDED.llm_count,
                 image_count = workspace_quota_reservations.image_count + EXCLUDED.image_count,
                 tts_request_count = workspace_quota_reservations.tts_request_count + EXCLUDED.tts_request_count,
                 reserved_estimated_cost_usd = workspace_quota_reservations.reserved_estimated_cost_usd
                   + EXCLUDED.reserved_estimated_cost_usd, updated_at = NOW()""",
            workspace_id, month_start, *increments, estimated_cost_usd,
        )
        await connection.execute(
            """INSERT INTO workspace_quota_reservation_owners
               (owner_id, workspace_id, period_start, operation_type, status, estimated_cost_usd)
               VALUES ($1,$2,$3,$4,'reserved',$5)""",
            owner_id, workspace_id, month_start, operation_type, estimated_cost_usd,
        )
        return True

    async def reservation_owner_id(self, task_id: str) -> str | None:
        pool = await get_pool()
        async with pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT owner_id, status FROM workspace_quota_reservation_owners WHERE owner_id = $1",
                task_id,
            )
            if row is not None and row["status"] == "cancelled":
                raise ValueError("Cancelled reservation owner")
            return row["owner_id"] if row is not None else None

    async def readmit_owned(
        self, owner_id: str, global_monthly_cost_usd: Decimal | None,
    ) -> bool:
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", 860)
                owner = await connection.fetchrow(
                    """SELECT * FROM workspace_quota_reservation_owners
                       WHERE owner_id = $1 FOR UPDATE""",
                    owner_id,
                )
                if owner is None or owner["status"] not in {"reserved", "consumed"}:
                    return False
                month_start = await connection.fetchval(
                    "SELECT date_trunc('month', NOW() AT TIME ZONE 'UTC')::timestamptz"
                )
                if owner["period_start"] == month_start:
                    return True
                workspace_id = int(owner["workspace_id"])
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                accounting = await connection.fetchrow(
                    """SELECT q.monthly_cost_usd,
                       (SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM usage_events
                        WHERE workspace_id = $1 AND created_at >= $2) AS workspace_settled,
                       (SELECT COALESCE(SUM(GREATEST(
                          estimated_cost_usd - settled_estimated_cost_usd, 0)), 0)
                        FROM workspace_quota_reservation_owners
                        WHERE workspace_id = $1 AND period_start = $2
                          AND status IN ('reserved', 'consumed', 'billable_unknown')) AS workspace_reserved,
                       (SELECT COALESCE(SUM(estimated_cost_usd), 0) FROM usage_events
                        WHERE created_at >= $2) AS global_settled,
                       (SELECT COALESCE(SUM(GREATEST(
                          estimated_cost_usd - settled_estimated_cost_usd, 0)), 0)
                        FROM workspace_quota_reservation_owners
                        WHERE period_start = $2
                          AND status IN ('reserved', 'consumed', 'billable_unknown')) AS global_reserved
                       FROM workspace_quotas q WHERE q.workspace_id = $1""",
                    workspace_id, month_start,
                )
                if accounting is None:
                    return False
                residual = max(
                    owner["estimated_cost_usd"] - owner["settled_estimated_cost_usd"],
                    Decimal("0"),
                )
                if accounting["workspace_settled"] + accounting["workspace_reserved"] + residual > accounting["monthly_cost_usd"]:
                    return False
                if (
                    global_monthly_cost_usd is not None
                    and accounting["global_settled"] + accounting["global_reserved"] + residual
                    > global_monthly_cost_usd
                ):
                    return False
                await connection.execute(
                    """UPDATE workspace_quota_reservation_owners SET period_start = $2
                       WHERE owner_id = $1""",
                    owner_id, month_start,
                )
                return True

    async def cancel_owned(self, owner_id: str) -> bool:
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                owner = await connection.fetchrow(
                    "SELECT workspace_id FROM workspace_quota_reservation_owners WHERE owner_id = $1",
                    owner_id,
                )
                if owner is None:
                    return False
                workspace_id = int(owner["workspace_id"])
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                owned = await connection.fetchrow(
                    """UPDATE workspace_quota_reservation_owners SET status = 'cancelled'
                       WHERE owner_id = $1 AND status = 'reserved'
                       RETURNING period_start, operation_type, estimated_cost_usd, status""",
                    owner_id,
                )
                if owned is None:
                    return False
                await connection.execute(
                    """UPDATE workspace_quota_reservations SET
                       llm_count = llm_count - $3,
                       image_count = image_count - $4,
                       tts_request_count = tts_request_count - $5,
                       reserved_estimated_cost_usd = GREATEST(reserved_estimated_cost_usd - $6, 0),
                       updated_at = NOW()
                       WHERE workspace_id = $1 AND period_start = $2""",
                    workspace_id, owned["period_start"],
                    int(owned["operation_type"] == "llm"),
                    int(owned["operation_type"] == "image_gen"),
                    int(owned["operation_type"] in {"tts", "stt", "render"}),
                    owned["estimated_cost_usd"],
                )
                return True

    async def settle_owned(self, owner_id: str, *, billable_unknown: bool = False) -> bool:
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                owner = await connection.fetchrow(
                    "SELECT workspace_id FROM workspace_quota_reservation_owners WHERE owner_id = $1",
                    owner_id,
                )
                if owner is None:
                    return False
                workspace_id = int(owner["workspace_id"])
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                status = "billable_unknown" if billable_unknown else "settled"
                source = await connection.fetchrow(
                    """SELECT period_start, operation_type, estimated_cost_usd, status
                       FROM workspace_quota_reservation_owners WHERE owner_id = $1 FOR UPDATE""",
                    owner_id,
                )
                if source is None or source["status"] not in {"reserved", "consumed"}:
                    return False
                if not billable_unknown and source["status"] == "reserved":
                    return False
                settled = await connection.fetchrow(
                    """UPDATE workspace_quota_reservation_owners SET status = $2
                       WHERE owner_id = $1 AND status IN ('reserved', 'consumed')
                       RETURNING period_start, operation_type, estimated_cost_usd""",
                    owner_id, status,
                )
                if settled is None:
                    return False
                keep = settled["estimated_cost_usd"] if billable_unknown else 0
                decrement_counts = source["status"] == "reserved"
                await connection.execute(
                    """UPDATE workspace_quota_reservations SET
                       llm_count = GREATEST(llm_count - $3, 0),
                       image_count = GREATEST(image_count - $4, 0),
                       tts_request_count = GREATEST(tts_request_count - $5, 0),
                       reserved_estimated_cost_usd = GREATEST(
                         reserved_estimated_cost_usd - $6 + $7, 0), updated_at = NOW()
                       WHERE workspace_id = $1 AND period_start = $2""",
                    workspace_id, settled["period_start"],
                    int(decrement_counts and settled["operation_type"] == "llm"),
                    int(decrement_counts and settled["operation_type"] == "image_gen"),
                    int(decrement_counts and settled["operation_type"] in {"tts", "stt", "render"}),
                    settled["estimated_cost_usd"], keep,
                )
                return True

    async def record_owned_event(self, row: dict[str, Any], owner_id: str) -> dict[str, Any]:
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                owner = await connection.fetchrow(
                    "SELECT workspace_id FROM workspace_quota_reservation_owners WHERE owner_id = $1",
                    owner_id,
                )
                if owner is None:
                    raise ValueError("Unknown reservation owner")
                workspace_id = int(owner["workspace_id"])
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                owned = await connection.fetchrow(
                    """SELECT period_start, operation_type, status
                       FROM workspace_quota_reservation_owners WHERE owner_id = $1 FOR UPDATE""",
                    owner_id,
                )
                if owned is None or row.get("workspace_id") != workspace_id or row.get("operation_type") != owned["operation_type"]:
                    raise ValueError("Usage event owner mismatch")
                if owned["status"] == "cancelled":
                    raise ValueError("Cancelled reservation owner")
                inserted = await connection.fetchrow(
                    """INSERT INTO usage_events (workspace_id, project_id, run_id, provider,
                       model_key, operation_type, input_tokens, output_tokens, image_count,
                       audio_seconds, estimated_cost_usd, cost_config_version, idempotency_key)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                       ON CONFLICT (idempotency_key) DO NOTHING
                       RETURNING *""",
                    row.get("workspace_id"), row.get("project_id"), row.get("run_id"),
                    row.get("provider"), row.get("model_key"), row.get("operation_type"),
                    row.get("input_tokens"), row.get("output_tokens"), row.get("image_count"),
                    row.get("audio_seconds"), row.get("estimated_cost_usd"),
                    row.get("cost_config_version"), row.get("idempotency_key"),
                )
                if inserted is None:
                    saved = await connection.fetchrow(
                        "SELECT * FROM usage_events WHERE idempotency_key = $1",
                        row.get("idempotency_key"),
                    )
                    if saved is None:
                        raise RuntimeError("Duplicate usage event disappeared during settlement")
                    return dict(saved)
                saved = inserted
                if owned["status"] == "reserved":
                    await connection.execute(
                        "UPDATE workspace_quota_reservation_owners SET status = 'consumed' WHERE owner_id = $1",
                        owner_id,
                    )
                    await connection.execute(
                        """UPDATE workspace_quota_reservations SET
                           llm_count = llm_count - $3, image_count = image_count - $4,
                           tts_request_count = tts_request_count - $5, updated_at = NOW()
                           WHERE workspace_id = $1 AND period_start = $2""",
                        workspace_id, owned["period_start"],
                        int(owned["operation_type"] == "llm"),
                        int(owned["operation_type"] == "image_gen"),
                        int(owned["operation_type"] in {"tts", "stt", "render"}),
                    )
                await connection.execute(
                    """UPDATE workspace_quota_reservation_owners
                       SET settled_estimated_cost_usd = LEAST(
                          estimated_cost_usd,
                          settled_estimated_cost_usd
                          + COALESCE($2::numeric, 0::numeric))
                       WHERE owner_id = $1""",
                    owner_id, saved["estimated_cost_usd"],
                )
                return dict(saved)

    async def authorize_owned_attempt(
        self, owner_id: str, attempt_id: str, estimated_cost_usd: Decimal,
    ) -> bool:
        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                owner = await connection.fetchrow(
                    "SELECT workspace_id FROM workspace_quota_reservation_owners WHERE owner_id = $1",
                    owner_id,
                )
                if owner is None:
                    return False
                await connection.execute(
                    "SELECT pg_advisory_xact_lock($1)", int(owner["workspace_id"])
                )
                existing = await connection.fetchval(
                    """SELECT estimated_cost_usd
                       FROM workspace_quota_reservation_attempts
                       WHERE owner_id = $1 AND attempt_id = $2""",
                    owner_id, attempt_id,
                )
                if existing is not None:
                    return existing == estimated_cost_usd
                inserted = await connection.fetchrow(
                    """INSERT INTO workspace_quota_reservation_attempts
                       (owner_id, attempt_id, estimated_cost_usd)
                       SELECT owner_id, $2, $3
                       FROM workspace_quota_reservation_owners owner
                       WHERE owner.owner_id = $1
                         AND owner.status IN ('reserved', 'consumed')
                         AND (SELECT COALESCE(SUM(attempt.estimated_cost_usd), 0)
                              FROM workspace_quota_reservation_attempts attempt
                              WHERE attempt.owner_id = owner.owner_id) + $3
                             <= owner.estimated_cost_usd
                       ON CONFLICT (owner_id, attempt_id) DO NOTHING
                       RETURNING estimated_cost_usd""",
                    owner_id, attempt_id, estimated_cost_usd,
                )
                return inserted is not None

    async def release_reservation(
        self, workspace_id: int, operation_type: str, units: int = 1
    ) -> None:
        await self._decrement_reservation(workspace_id, operation_type, units)

    async def cancel_reservation(
        self, workspace_id: int, operation_type: str, units: int = 1
    ) -> None:
        await self._decrement_reservation(workspace_id, operation_type, units)

    async def _decrement_reservation(
        self, workspace_id: int, operation_type: str, units: int
    ) -> None:
        if operation_type not in {"llm", "image_gen", "tts", "stt", "render"}:
            return
        decrement = max(0, int(units))
        if decrement == 0:
            return

        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
                month_start = await connection.fetchval(
                    "SELECT date_trunc('month', NOW() AT TIME ZONE 'UTC')::timestamptz"
                )
                if month_start is None:
                    return

                llm_decrement = decrement if operation_type == "llm" else 0
                image_decrement = decrement if operation_type == "image_gen" else 0
                tts_decrement = decrement if operation_type in {"tts", "stt", "render"} else 0
                await connection.execute(
                    """
                    UPDATE workspace_quota_reservations
                    SET
                        llm_count = GREATEST(llm_count - $3, (
                            SELECT COUNT(*) FROM workspace_quota_reservation_owners
                            WHERE workspace_id = $1 AND period_start = $2
                              AND status = 'reserved' AND operation_type = 'llm'
                        )),
                        image_count = GREATEST(image_count - $4, (
                            SELECT COUNT(*) FROM workspace_quota_reservation_owners
                            WHERE workspace_id = $1 AND period_start = $2
                              AND status = 'reserved' AND operation_type = 'image_gen'
                        )),
                        tts_request_count = GREATEST(tts_request_count - $5, (
                            SELECT COUNT(*) FROM workspace_quota_reservation_owners
                            WHERE workspace_id = $1 AND period_start = $2
                              AND status = 'reserved' AND operation_type IN ('tts', 'stt', 'render')
                        )),
                        updated_at = NOW()
                    WHERE workspace_id = $1 AND period_start = $2
                    """,
                    workspace_id,
                    month_start,
                    llm_decrement,
                    image_decrement,
                    tts_decrement,
                )
