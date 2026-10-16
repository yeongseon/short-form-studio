import anyio
import pytest

from creator_service.usage_service import InMemoryUsageStorage, UsageService


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
async def test_operator_kill_switch_blocks_new_billable_work(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given the global billable-work switch is disabled.
    monkeypatch.setenv("BILLABLE_PROVIDER_CALLS_ENABLED", "false")
    service = UsageService(InMemoryUsageStorage())

    # When a new reservation is requested, then admission is blocked while reads still work.
    assert not await service.reserve_owned(1, "llm", "blocked", estimated_cost_usd=0.01)
    assert (await service.get_monthly_summary(1)).total_estimated_cost_usd == 0.0


@pytest.mark.asyncio
async def test_unset_cost_model_is_rejected_conservatively() -> None:
    # Given an operation without a configured bounded estimate.
    service = UsageService(InMemoryUsageStorage())

    # When admission cannot determine its maximum spend, then it is rejected.
    assert not await service.reserve_owned(1, "unpriced-provider", "task")


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
