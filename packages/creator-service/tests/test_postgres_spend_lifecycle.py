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


async def test_postgres_rollover_and_settlement_share_lock_order(quota_pool: object) -> None:
    # Given a stale owner with one durable provider event.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_cost_usd=Decimal("2"))
    assert await service.reserve_owned(1, "llm", "contended", estimated_cost_usd=Decimal("1"))
    await quota_pool.execute(
        "UPDATE workspace_quota_reservation_owners SET period_start = $2 WHERE owner_id = $1",
        "contended", datetime(2000, 1, 1, tzinfo=timezone.utc),
    )
    await service.record_usage(
        1, 1, "fixture", "fixture", "llm", estimated_cost_usd=Decimal("0.5"),
        idempotency_key="contended:event", reservation_owner_id="contended",
    )
    # When rollover admission and settlement contend on the same owner.
    async with anyio.create_task_group() as group:
        group.start_soon(lambda: service.readmit_owned("contended"))
        group.start_soon(lambda: service.settle_owned("contended"))

    # Then both transactions complete without deadlock and the owner is terminal.
    status = await quota_pool.fetchval(
        "SELECT status FROM workspace_quota_reservation_owners WHERE owner_id = $1", "contended"
    )
    assert status in {"settled", "billable_unknown"}


async def test_postgres_multi_scene_success_consumes_reserved_units_one_by_one(
    quota_pool: object,
) -> None:
    # Given a migrated PostgreSQL owner reserving three scene units.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_image_generations=3, monthly_cost_usd=Decimal("3"))
    assert await service.reserve_owned(
        1, "image_gen", "fanout-success", estimated_cost_usd=Decimal("3"), units=3,
    )

    # When two of three scene events become durable.
    for scene in range(2):
        await service.record_usage(
            1, 1, "fixture", "fixture", "image_gen", image_count=1,
            estimated_cost_usd=Decimal("1"), idempotency_key=f"success:{scene}",
            reservation_owner_id="fanout-success",
        )

    # Then only one unit remains reserved and the owner is not consumed early.
    owner = await quota_pool.fetchrow(
        "SELECT status, reserved_units FROM workspace_quota_reservation_owners WHERE owner_id = $1",
        "fanout-success",
    )
    assert dict(owner) == {"status": "reserved", "reserved_units": 1}
    assert await quota_pool.fetchval(
        "SELECT image_count FROM workspace_quota_reservations WHERE workspace_id = 1",
    ) == 1
    await service.record_usage(
        1, 1, "fixture", "fixture", "image_gen", image_count=1,
        estimated_cost_usd=Decimal("1"), idempotency_key="success:2",
        reservation_owner_id="fanout-success",
    )
    assert await quota_pool.fetchval(
        "SELECT status FROM workspace_quota_reservation_owners WHERE owner_id = $1",
        "fanout-success",
    ) == "consumed"


async def test_postgres_multi_scene_cancel_releases_all_remaining_units(quota_pool: object) -> None:
    # Given a three-scene reservation with no durable usage.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_image_generations=3, monthly_cost_usd=Decimal("3"))
    assert await service.reserve_owned(
        1, "image_gen", "fanout-cancel", estimated_cost_usd=Decimal("3"), units=3,
    )

    # When it is cancelled before provider execution.
    assert await service.cancel_owned("fanout-cancel")

    # Then every reserved unit is returned.
    assert await quota_pool.fetchval(
        "SELECT image_count FROM workspace_quota_reservations WHERE workspace_id = 1",
    ) == 0


async def test_postgres_queued_revocation_cancels_owned_reservation(quota_pool: object) -> None:
    # Given a queued delivery that has not authorized provider work.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_cost_usd=Decimal("0.10"))
    assert await service.reserve_owned(
        1, "image_gen", "queued-revoke", estimated_cost_usd=Decimal("0.10"),
    )

    # When duplicate API/signal cleanup finalizes the revocation.
    assert await service.finalize_revoked_owned("queued-revoke")
    assert not await service.finalize_revoked_owned("queued-revoke")

    # Then its reservation is cancelled and replacement spend is admitted.
    assert await quota_pool.fetchval(
        "SELECT status FROM workspace_quota_reservation_owners WHERE owner_id=$1",
        "queued-revoke",
    ) == "cancelled"
    assert await service.reserve_owned(
        1, "image_gen", "queued-replacement", estimated_cost_usd=Decimal("0.10"),
    )


async def test_postgres_active_revocation_retains_authorized_exposure(quota_pool: object) -> None:
    # Given an active delivery with durable provider authorization.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_cost_usd=Decimal("0.10"))
    assert await service.reserve_owned(
        1, "image_gen", "active-revoke", estimated_cost_usd=Decimal("0.10"),
    )
    assert await service.authorize_owned_attempt(
        "active-revoke", "attempt-1", Decimal("0.10"),
    )

    # When duplicate API/signal cleanup finalizes the revocation.
    assert await service.finalize_revoked_owned("active-revoke")
    assert not await service.finalize_revoked_owned("active-revoke")

    # Then exposure becomes unknown, remains charged, and rejects replacement spend.
    owner = await quota_pool.fetchrow(
        "SELECT status, estimated_cost_usd FROM workspace_quota_reservation_owners "
        "WHERE owner_id=$1",
        "active-revoke",
    )
    assert dict(owner) == {
        "status": "billable_unknown",
        "estimated_cost_usd": Decimal("0.100000"),
    }
    assert not await service.reserve_owned(
        1, "image_gen", "active-replacement", estimated_cost_usd=Decimal("0.10"),
    )


async def test_postgres_accounted_revocation_releases_unstarted_quote_capacity(
    quota_pool: object,
) -> None:
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_cost_usd=Decimal("1"))
    assert await service.reserve_owned(
        1, "image_gen", "accounted-revoke", estimated_cost_usd=Decimal("1"),
    )
    assert await service.authorize_owned_attempt(
        "accounted-revoke", "accounted-revoke:0", Decimal("0.40"),
    )
    await service.record_usage(
        1, 1, "fixture", "fixture", "image_gen", image_count=1,
        estimated_cost_usd=Decimal("0.40"), idempotency_key="accounted-revoke:0",
        reservation_owner_id="accounted-revoke",
        reservation_attempt_id="accounted-revoke:0",
    )

    assert await service.finalize_revoked_owned("accounted-revoke")

    owner = await quota_pool.fetchrow(
        "SELECT status, estimated_cost_usd FROM workspace_quota_reservation_owners "
        "WHERE owner_id=$1",
        "accounted-revoke",
    )
    assert dict(owner) == {
        "status": "settled",
        "estimated_cost_usd": Decimal("0.400000"),
    }
    assert await service.reserve_owned(
        1, "image_gen", "accounted-replacement", estimated_cost_usd=Decimal("0.60"),
    )


async def test_postgres_mixed_revocation_retains_only_unknown_attempt(
    quota_pool: object,
) -> None:
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_cost_usd=Decimal("1"))
    assert await service.reserve_owned(
        1, "image_gen", "mixed-revoke", estimated_cost_usd=Decimal("1"),
    )
    assert await service.authorize_owned_attempt(
        "mixed-revoke", "mixed-revoke:accounted", Decimal("0.40"),
    )
    assert await service.authorize_owned_attempt(
        "mixed-revoke", "mixed-revoke:authorized", Decimal("0.20"),
    )
    await service.record_usage(
        1, 1, "fixture", "fixture", "image_gen", image_count=1,
        estimated_cost_usd=Decimal("0.40"), idempotency_key="mixed-revoke:accounted",
        reservation_owner_id="mixed-revoke",
        reservation_attempt_id="mixed-revoke:accounted",
    )

    assert await service.finalize_revoked_owned("mixed-revoke")

    owner = await quota_pool.fetchrow(
        "SELECT status, estimated_cost_usd FROM workspace_quota_reservation_owners "
        "WHERE owner_id=$1",
        "mixed-revoke",
    )
    assert dict(owner) == {
        "status": "billable_unknown",
        "estimated_cost_usd": Decimal("0.600000"),
    }
    assert await service.reserve_owned(
        1, "image_gen", "mixed-replacement", estimated_cost_usd=Decimal("0.40"),
    )
    assert not await service.reserve_owned(
        1, "image_gen", "mixed-overflow", estimated_cost_usd=Decimal("0.01"),
    )


async def test_postgres_partial_multi_scene_settlement_releases_remaining_units(
    quota_pool: object,
) -> None:
    # Given one durable scene from a three-scene reservation.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_image_generations=3, monthly_cost_usd=Decimal("3"))
    assert await service.reserve_owned(
        1, "image_gen", "fanout-partial", estimated_cost_usd=Decimal("3"), units=3,
    )
    await service.record_usage(
        1, 1, "fixture", "fixture", "image_gen", image_count=1,
        estimated_cost_usd=Decimal("1"), idempotency_key="partial:0",
        reservation_owner_id="fanout-partial",
    )

    # When terminal success settles the partially completed owner.
    assert await service.settle_owned("fanout-partial")

    # Then both unused units are released and the owner is terminal.
    owner = await quota_pool.fetchrow(
        "SELECT status, reserved_units FROM workspace_quota_reservation_owners WHERE owner_id = $1",
        "fanout-partial",
    )
    assert dict(owner) == {"status": "settled", "reserved_units": 0}
    assert await quota_pool.fetchval(
        "SELECT image_count FROM workspace_quota_reservations WHERE workspace_id = 1",
    ) == 0


async def test_postgres_multi_scene_rollover_moves_all_remaining_units(quota_pool: object) -> None:
    # Given a three-scene owner whose full reservation belongs to a prior month.
    service = UsageService(PostgresUsageStorage())
    await service.set_quota(1, monthly_image_generations=3, monthly_cost_usd=Decimal("3"))
    assert await service.reserve_owned(
        1, "image_gen", "fanout-rollover", estimated_cost_usd=Decimal("3"), units=3,
    )
    current_period = await quota_pool.fetchval(
        "SELECT period_start FROM workspace_quota_reservation_owners WHERE owner_id = $1",
        "fanout-rollover",
    )
    old_period = datetime(2000, 1, 1, tzinfo=timezone.utc)
    await quota_pool.execute(
        "UPDATE workspace_quota_reservation_owners SET period_start = $2 WHERE owner_id = $1",
        "fanout-rollover", old_period,
    )
    await quota_pool.execute(
        "UPDATE workspace_quota_reservations SET period_start = $2 WHERE workspace_id = 1 AND period_start = $1",
        current_period, old_period,
    )

    # When the worker re-admits the stale owner.
    assert await service.readmit_owned("fanout-rollover")

    # Then all three units move to the current period and exhaust its capacity.
    assert await quota_pool.fetchval(
        "SELECT image_count FROM workspace_quota_reservations WHERE workspace_id = 1 AND period_start = $1",
        current_period,
    ) == 3
    assert not await service.reserve_owned(
        1, "image_gen", "rollover-overflow", estimated_cost_usd=Decimal("0.01"), units=1,
    )
