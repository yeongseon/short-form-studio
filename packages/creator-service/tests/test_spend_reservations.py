import anyio
import pytest
from decimal import Decimal
from datetime import datetime, timezone

from creator_service.usage_service import (
    InMemoryUsageStorage, ReservationQuote, UsageService,
)


@pytest.mark.asyncio
async def test_concurrent_spend_reservations_admit_exactly_one() -> None:
    # Given settled estimated spend of 49.9 against a budget of 50.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=50.0)
    await service.record_usage(1, 1, "fixture", "fixture", "llm", estimated_cost_usd=49.9)
    ready = anyio.Event()
    results: list[bool] = []

    async def reserve(owner_id: str) -> None:
        await ready.wait()
        results.append(await service.reserve_owned(1, "llm", owner_id, estimated_cost_usd=0.1))

    # When two deliveries cross the barrier together.
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(reserve, "attempt-a")
        tasks.start_soon(reserve, "attempt-b")
        ready.set()

    # Then settled + reserved + new estimate never exceeds the budget.
    assert sorted(results) == [False, True]


@pytest.mark.asyncio
async def test_redelivery_does_not_double_reserve_spend() -> None:
    # Given one delivery reserved at the full workspace budget.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=1.0)
    assert await service.reserve_owned(1, "llm", "attempt-a", estimated_cost_usd=1.0)

    # When the same task/attempt is delivered again.
    admitted = await service.reserve_owned(1, "llm", "attempt-a", estimated_cost_usd=1.0)

    # Then it is idempotently admitted without making room for another owner.
    assert admitted
    assert not await service.reserve_owned(1, "llm", "attempt-b", estimated_cost_usd=0.01)


@pytest.mark.asyncio
async def test_cancelled_owner_is_not_readmitted_by_redelivery() -> None:
    # Given an owner whose pre-provider reservation was cancelled.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=1.0)
    assert await service.reserve_owned(1, "llm", "attempt-a", estimated_cost_usd=1.0)
    assert await service.cancel_owned("attempt-a")

    # When the cancelled delivery is redelivered.
    admitted = await service.reserve_owned(1, "llm", "attempt-a", estimated_cost_usd=1.0)

    # Then its terminal owner state rejects it while a new owner can use the capacity.
    assert not admitted
    assert await service.reserve_owned(1, "llm", "attempt-b", estimated_cost_usd=1.0)


@pytest.mark.asyncio
async def test_pre_execution_cancel_releases_spend_but_unknown_keeps_it() -> None:
    # Given two independent workspaces with one-dollar budgets.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=1.0)
    await service.set_quota(2, monthly_cost_usd=1.0)
    assert await service.reserve_owned(1, "llm", "pre-exec", estimated_cost_usd=1.0)
    assert await service.reserve_owned(2, "llm", "provider-started", estimated_cost_usd=1.0)

    # When one fails before execution and the other has an unknown provider outcome.
    assert await service.cancel_owned("pre-exec")
    assert await service.settle_owned_unknown("provider-started")

    # Then only the definitely unbilled reservation is returned.
    assert await service.reserve_owned(1, "llm", "replacement", estimated_cost_usd=1.0)
    assert not await service.reserve_owned(2, "llm", "unsafe-replacement", estimated_cost_usd=0.01)


@pytest.mark.asyncio
async def test_success_settlement_releases_unused_approved_spend_once() -> None:
    # Given a bounded multi-call job that records less than its approved maximum.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=1.0)
    assert await service.reserve_owned(1, "image_gen", "fanout", estimated_cost_usd=1.0)
    await service.record_usage(
        1, 1, "fixture", "fixture", "image_gen", image_count=1,
        estimated_cost_usd=0.4, idempotency_key="fanout:scene-1", reservation_owner_id="fanout",
    )

    # When terminal success is settled twice after redelivery.
    assert await service.settle_owned("fanout")
    assert not await service.settle_owned("fanout")

    # Then only settled usage remains and unused approval can be reused.
    assert await service.reserve_owned(1, "image_gen", "next", estimated_cost_usd=0.6)
    assert not await service.reserve_owned(1, "image_gen", "overflow", estimated_cost_usd=0.01)


@pytest.mark.asyncio
async def test_duplicate_event_does_not_settle_owner_twice() -> None:
    # Given a one-dollar approval and a 40-cent provider event.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=1.0)
    assert await service.reserve_owned(1, "image_gen", "fanout", estimated_cost_usd=1.0)
    event = {
        "workspace_id": 1,
        "run_id": 1,
        "provider": "fixture",
        "model_key": "fixture",
        "operation_type": "image_gen",
        "image_count": 1,
        "estimated_cost_usd": 0.4,
        "idempotency_key": "fanout:scene-1",
        "reservation_owner_id": "fanout",
    }

    # When the same event is delivered twice.
    await service.record_usage(**event)
    await service.record_usage(**event)

    # Then only 40 cents is accounted and the remaining 60-cent exposure stays reserved.
    assert not await service.reserve_owned(1, "image_gen", "premature", estimated_cost_usd=0.4)


@pytest.mark.asyncio
async def test_success_retains_authorized_attempt_without_usage_event() -> None:
    # Given two provider attempts consumed all approved capacity.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=2.0)
    assert await service.reserve_owned(1, "image_gen", "retry", estimated_cost_usd=2.0)
    assert await service.authorize_owned_attempt("retry", "attempt-1", Decimal("1.0"))
    assert await service.authorize_owned_attempt("retry", "attempt-2", Decimal("1.0"))

    # When only the successful retry has a durable usage event before terminal settlement.
    await service.record_usage(
        workspace_id=1, run_id=1, provider="fixture", model_key="fixture",
        operation_type="image_gen", image_count=1, estimated_cost_usd=1.0,
        idempotency_key="retry:event", reservation_owner_id="retry",
        reservation_attempt_id="attempt-2",
    )
    assert await service.settle_owned("retry")

    # Then the first authorized attempt remains billable-unknown and blocks replacement.
    assert not await service.reserve_owned(1, "image_gen", "replacement", estimated_cost_usd=1.0)


@pytest.mark.asyncio
async def test_operator_kill_switch_blocks_new_billable_work(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given the global billable-work switch is disabled.
    monkeypatch.setenv("BILLABLE_PROVIDER_CALLS_ENABLED", "false")
    service = UsageService(InMemoryUsageStorage())

    # When a new reservation is requested, then admission is blocked while reads still work.
    assert not await service.reserve_owned(1, "llm", "blocked", estimated_cost_usd=0.01)
    assert (await service.get_monthly_summary(1)).total_estimated_cost_usd == 0.0


@pytest.mark.asyncio
async def test_operator_kill_switch_blocks_queued_owner_before_provider_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given work was reserved while provider calls were enabled.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=1.0)
    assert await service.reserve_owned(1, "llm", "queued", estimated_cost_usd=1.0)

    # When the operator disables billable calls before the queued work starts.
    monkeypatch.setenv("BILLABLE_PROVIDER_CALLS_ENABLED", "false")

    # Then neither delivery admission nor provider-attempt authorization may proceed.
    assert not await service.readmit_owned("queued")
    assert not await service.authorize_owned_attempt("queued", "attempt-1", Decimal("0.1"))


@pytest.mark.asyncio
async def test_unset_cost_model_is_rejected_conservatively() -> None:
    # Given an operation without a configured bounded estimate.
    service = UsageService(InMemoryUsageStorage())

    # When admission cannot determine its maximum spend, then it is rejected.
    assert not await service.reserve_owned(1, "unpriced-provider", "task")


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
async def test_non_finite_reservation_estimate_is_rejected(invalid: Decimal) -> None:
    # Given a non-finite monetary estimate from an admission boundary.
    service = UsageService(InMemoryUsageStorage())

    # When reservation admission parses the estimate, then it rejects it before arithmetic.
    assert not await service.reserve_owned(1, "llm", "invalid", estimated_cost_usd=invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity"])
async def test_non_finite_global_budget_is_rejected_at_startup(
    monkeypatch: pytest.MonkeyPatch, invalid: str,
) -> None:
    # Given an invalid global monetary configuration.
    monkeypatch.setenv("GLOBAL_MONTHLY_ESTIMATED_BUDGET_USD", invalid)
    service = UsageService(InMemoryUsageStorage())

    # When a billable reservation loads configuration, then startup validation fails closed.
    with pytest.raises(ValueError, match="GLOBAL_MONTHLY_ESTIMATED_BUDGET_USD"):
        await service.reserve_owned(1, "llm", "invalid", estimated_cost_usd=Decimal("0.1"))


@pytest.mark.asyncio
async def test_global_budget_blocks_only_new_billable_reservations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given one workspace has consumed the operator-wide estimated budget.
    monkeypatch.setenv("GLOBAL_MONTHLY_ESTIMATED_BUDGET_USD", "1.0")
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=10.0)
    await service.set_quota(2, monthly_cost_usd=10.0)
    assert await service.reserve_owned(1, "llm", "first", estimated_cost_usd=1.0)

    # When another workspace requests billable admission, then it is rejected globally.
    assert not await service.reserve_owned(2, "llm", "second", estimated_cost_usd=0.01)
    assert (await service.get_monthly_summary(2)).total_estimated_cost_usd == 0.0


@pytest.mark.asyncio
async def test_stale_owner_is_readmitted_before_provider_execution() -> None:
    # Given an active owner admitted in the prior month and a full current-month budget.
    storage = InMemoryUsageStorage()
    service = UsageService(storage)
    await service.set_quota(1, monthly_cost_usd=1.0)
    assert await service.reserve_owned(1, "llm", "stale", estimated_cost_usd=Decimal("1"))
    owner = storage._owned["stale"]
    storage._owned["stale"] = (
        owner[0], datetime(2000, 1, 1, tzinfo=timezone.utc), *owner[2:],
    )
    await service.record_usage(
        1, 1, "fixture", "fixture", "llm", estimated_cost_usd=1.0,
    )

    # When the worker re-admits its stale reservation for the current month.
    admitted = await service.readmit_owned("stale")

    # Then it is rejected before another provider call can start.
    assert not admitted


@pytest.mark.asyncio
async def test_stale_owner_count_is_moved_to_current_month() -> None:
    # Given a stale image reservation and one available image in the current month.
    storage = InMemoryUsageStorage()
    service = UsageService(storage)
    await service.set_quota(1, monthly_image_generations=1, monthly_cost_usd=10.0)
    assert await service.reserve_owned(1, "image_gen", "stale", estimated_cost_usd=Decimal("1"))
    owner = storage._owned["stale"]
    old_period = datetime(2000, 1, 1, tzinfo=timezone.utc)
    storage._reservations[(1, old_period)] = storage._reservations.pop((owner[0], owner[1]))
    storage._owned["stale"] = (owner[0], old_period, *owner[2:])

    # When the stale owner is re-admitted into the current month.
    assert await service.readmit_owned("stale")

    # Then its count consumes current-month capacity and no replacement is admitted.
    assert not await service.reserve_owned(
        1, "image_gen", "replacement", estimated_cost_usd=Decimal("1")
    )


@pytest.mark.asyncio
async def test_image_fanout_reserves_each_scene_count_unit() -> None:
    # Given an image quota of one operation.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_image_generations=1, monthly_cost_usd=10.0)

    # When a three-scene fan-out requests three image units.
    admitted = await service.reserve_owned(
        1, "image_gen", "fanout", estimated_cost_usd=Decimal("3"), units=3
    )

    # Then admission is rejected before any scene provider can run.
    assert not admitted


@pytest.mark.asyncio
async def test_provider_attempts_atomically_consume_only_approved_capacity() -> None:
    # Given a quote approving two ten-cent provider attempts.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=1.0)
    assert await service.reserve_owned(
        1, "image_gen", "task", estimated_cost_usd=Decimal("0.20")
    )

    # When attempts are authorized, duplicate delivery is idempotent and excess exposure is denied.
    assert await service.authorize_owned_attempt("task", "task:0", Decimal("0.10"))
    assert await service.authorize_owned_attempt("task", "task:0", Decimal("0.10"))
    assert await service.authorize_owned_attempt("task", "task:1", Decimal("0.10"))
    assert not await service.authorize_owned_attempt("task", "task:2", Decimal("0.10"))


@pytest.mark.asyncio
async def test_accounted_attempt_releases_only_unstarted_quote_capacity() -> None:
    # Given one started attempt inside a larger conservative task quote.
    service = UsageService(InMemoryUsageStorage())
    await service.set_quota(1, monthly_cost_usd=Decimal("1"))
    assert await service.reserve_owned(
        1, "image_gen", "task", estimated_cost_usd=Decimal("1")
    )
    assert await service.authorize_owned_attempt("task", "task:scene:0", Decimal("0.40"))
    await service.record_usage(
        1, 1, "fixture", "fixture", "image_gen", image_count=1,
        estimated_cost_usd=Decimal("0.40"), idempotency_key="task:scene:0",
        reservation_owner_id="task", reservation_attempt_id="task:scene:0",
    )

    # When the task settles, then only its accounted event remains charged.
    assert await service.settle_owned("task")
    assert await service.reserve_owned(
        1, "image_gen", "replacement", estimated_cost_usd=Decimal("0.60")
    )


def test_scene_quote_bounds_fanout_internal_attempts_and_retries() -> None:
    # Given two scenes, three internal attempts, and five Celery retries.
    quote = ReservationQuote.bounded(
        unit_cost_usd=Decimal("0.04"), units=2, internal_attempts=3, deliveries=6,
    )

    # When the quote is calculated, then every possible provider attempt is covered.
    assert quote.maximum_cost_usd == Decimal("1.440000")


@pytest.mark.parametrize("units", [None, 0, -1])
def test_quote_rejects_unbounded_or_empty_work(units: int | None) -> None:
    # Given work whose maximum units cannot be positively bounded.
    # When a quote is requested, then admission rejects the task before dispatch.
    with pytest.raises(ValueError, match="units"):
        ReservationQuote.bounded(
            unit_cost_usd=Decimal("0.04"), units=units,
            internal_attempts=1, deliveries=1,
        )
