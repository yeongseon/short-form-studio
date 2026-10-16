from datetime import datetime, timezone
from decimal import Decimal

import anyio
import pytest

from creator_service.postgres_usage_storage import PostgresUsageStorage
from creator_service.usage_service import UsageService

from .quota_dispatch_support import quota_pool as quota_pool

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.parametrize("quota_pool", ["postgres"], indirect=True),
]


async def test_concurrent_admission_and_duplicate_settlement_on_migrated_postgres(
    quota_pool: object,
) -> None:
    # Given migrated PostgreSQL with only one ten-cent reservation available.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_cost_usd=Decimal("0.10"))
    ready = anyio.Event()
    admissions: list[bool] = []

    async def reserve(owner_id: str) -> None:
        await ready.wait()
        admissions.append(await service.reserve_owned(
            1, "image_gen", owner_id, estimated_cost_usd=Decimal("0.10")
        ))

    # When two owners contend and the winner's event is delivered twice.
    async with anyio.create_task_group() as group:
        group.start_soon(reserve, "owner-a")
        group.start_soon(reserve, "owner-b")
        ready.set()
    winner = "owner-a" if await service.reservation_owner_id("owner-a") else "owner-b"
    for _ in range(2):
        await service.record_usage(
            1, 1, "fixture", "fixture", "image_gen", image_count=1,
            estimated_cost_usd=Decimal("0.04"), idempotency_key="provider-attempt",
            reservation_owner_id=winner,
        )

    # Then admission and settlement remain exactly once in the real database.
    assert sorted(admissions) == [False, True]
    assert await quota_pool.fetchval("SELECT count(*) FROM usage_events") == 1
    assert await quota_pool.fetchval(
        "SELECT settled_estimated_cost_usd FROM workspace_quota_reservation_owners WHERE owner_id = $1",
        winner,
    ) == Decimal("0.040000")


async def test_postgres_rollover_readmission_rechecks_current_budget(quota_pool: object) -> None:
    # Given an active owner moved to a prior month and current-month spend at the limit.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_cost_usd=Decimal("1"))
    assert await service.reserve_owned(1, "llm", "stale", estimated_cost_usd=Decimal("1"))
    await quota_pool.execute(
        "UPDATE workspace_quota_reservation_owners SET period_start = $2 WHERE owner_id = $1",
        "stale", datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    await service.record_usage(
        1, 1, "fixture", "fixture", "llm", estimated_cost_usd=Decimal("1")
    )

    # When the worker re-admits before the next attempt, then current-month limits reject it.
    assert not await service.readmit_owned("stale")
