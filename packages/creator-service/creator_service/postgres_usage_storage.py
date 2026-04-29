from __future__ import annotations

from datetime import datetime
from typing import Any

from .db import fetch_all, fetch_one, get_pool


class PostgresUsageStorage:
    async def record_event(self, row: dict[str, Any]) -> dict[str, Any]:
        saved = await fetch_one(
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
                cost_config_version
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            RETURNING *
            """,
            row.get("workspace_id"),
            row.get("project_id"),
            row.get("run_id"),
            row.get("provider"),
            row.get("model_key"),
            row.get("operation_type"),
            row.get("input_tokens"),
            row.get("output_tokens"),
            row.get("image_count"),
            row.get("audio_seconds"),
            row.get("estimated_cost_usd"),
            row.get("cost_config_version"),
        )
        if saved is None:
            raise ValueError("Failed to create usage event")
        return saved

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
                monthly_tts_seconds,
                monthly_cost_usd
            )
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (workspace_id)
            DO UPDATE SET
                monthly_llm_calls = EXCLUDED.monthly_llm_calls,
                monthly_image_generations = EXCLUDED.monthly_image_generations,
                monthly_tts_seconds = EXCLUDED.monthly_tts_seconds,
                monthly_cost_usd = EXCLUDED.monthly_cost_usd,
                updated_at = NOW()
            RETURNING *
            """,
            workspace_id,
            quota["monthly_llm_calls"],
            quota["monthly_image_generations"],
            quota["monthly_tts_seconds"],
            quota["monthly_cost_usd"],
        )
        if saved is None:
            raise ValueError(f"Failed to set quota for workspace {workspace_id}")
        return saved

    async def try_reserve_quota(self, workspace_id: int, operation_type: str) -> bool:
        if operation_type not in {"llm", "image_gen", "tts", "stt", "render"}:
            return True

        pool = await get_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute("SELECT pg_advisory_xact_lock($1)", workspace_id)
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
                            monthly_tts_seconds,
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
                        COALESCE(SUM(CASE WHEN operation_type = 'tts' THEN COALESCE(audio_seconds, 0) ELSE 0 END), 0)::double precision AS tts_seconds
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
                    SELECT llm_count, image_count, tts_count
                    FROM workspace_quota_reservations
                    WHERE workspace_id = $1 AND period_start = $2
                    """,
                    workspace_id,
                    month_start,
                )
                reserved_llm = int(reservation_row["llm_count"]) if reservation_row else 0
                reserved_image = int(reservation_row["image_count"]) if reservation_row else 0
                reserved_tts = int(reservation_row["tts_count"]) if reservation_row else 0

                allowed = True
                if operation_type == "llm":
                    allowed = int(usage_row["llm_count"]) + reserved_llm < int(
                        quota["monthly_llm_calls"]
                    )
                elif operation_type == "image_gen":
                    allowed = int(usage_row["image_count"]) + reserved_image < int(
                        quota["monthly_image_generations"]
                    )
                # STT/render intentionally share the audio reservation bucket with
                # TTS because workspace_quota_reservations currently has only
                # llm_count, image_count, and tts_count columns.
                elif operation_type in {"tts", "stt", "render"}:
                    allowed = float(usage_row["tts_seconds"]) + reserved_tts < int(
                        quota["monthly_tts_seconds"]
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
                        tts_count
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (workspace_id, period_start)
                    DO UPDATE SET
                        llm_count = workspace_quota_reservations.llm_count + EXCLUDED.llm_count,
                        image_count = workspace_quota_reservations.image_count + EXCLUDED.image_count,
                        tts_count = workspace_quota_reservations.tts_count + EXCLUDED.tts_count,
                        updated_at = NOW()
                    """,
                    workspace_id,
                    month_start,
                    llm_increment,
                    image_increment,
                    tts_increment,
                )
                return True

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
                        llm_count = GREATEST(0, llm_count - $3),
                        image_count = GREATEST(0, image_count - $4),
                        tts_count = GREATEST(0, tts_count - $5),
                        updated_at = NOW()
                    WHERE workspace_id = $1 AND period_start = $2
                    """,
                    workspace_id,
                    month_start,
                    llm_decrement,
                    image_decrement,
                    tts_decrement,
                )
