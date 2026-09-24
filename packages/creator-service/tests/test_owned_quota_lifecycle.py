import pytest

from creator_service.postgres_usage_storage import PostgresUsageStorage
from creator_service.usage_service import InMemoryUsageStorage, UsageService
from creator_service import usage_service as usage_module

from .quota_dispatch_support import quota_pool as quota_pool


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_cancel_owner_releases_only_its_reserved_capacity(quota_pool: object) -> None:
    # Given two deliveries that reserve the same workspace's shared audio bucket.
    storage = PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    service = UsageService(storage)
    await service.set_quota(1, monthly_tts_requests=2)
    assert await service.reserve_owned(1, "tts", "delivery-a")
    assert await service.reserve_owned(1, "tts", "delivery-b")

    # When the first delivery is cancelled twice.
    assert await service.cancel_owned("delivery-a")
    assert not await service.cancel_owned("delivery-a")

    # Then the other delivery still occupies one of two slots.
    assert await service.reserve_owned(1, "tts", "delivery-c")
    assert not await service.reserve_owned(1, "tts", "delivery-d")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_usage_consumes_only_its_owner_once(quota_pool: object) -> None:
    # Given two pending TTS deliveries with distinct owner IDs.
    storage = PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    service = UsageService(storage)
    await service.set_quota(1, monthly_tts_requests=2)
    assert await service.reserve_owned(1, "tts", "delivery-a")
    assert await service.reserve_owned(1, "tts", "delivery-b")

    # When A reports usage twice with the same reservation owner and idempotency key.
    for _ in range(2):
        await service.record_usage(
            1, 1, "edge_tts", "edge", "tts", idempotency_key="delivery-a",
            reservation_owner_id="delivery-a",
        )

    # Then A consumes one slot and cannot accidentally release B's capacity.
    assert len(await storage.list_by_run(1, workspace_id=1)) == 1
    assert not await service.reserve_owned(1, "tts", "delivery-c")
    assert await service.cancel_owned("delivery-b")
    assert await service.reserve_owned(1, "tts", "delivery-c")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_unknown_owner_cannot_release_another_delivery(quota_pool: object) -> None:
    # Given an anonymous reservation held by a different delivery.
    storage = PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    service = UsageService(storage)
    await service.set_quota(1, monthly_tts_requests=1)
    assert (await service.check_quota(1, "tts"))[0]

    # When a usage event claims a nonexistent owner token.
    with pytest.raises(ValueError, match="reservation owner"):
        await service.record_usage(
            1, 1, "edge_tts", "edge", "tts", idempotency_key="unknown-owner",
            reservation_owner_id="unknown-owner",
        )

    # Then the anonymous reservation still occupies capacity and no usage was saved.
    assert not (await service.check_quota(1, "tts"))[0]
    assert await storage.list_by_run(1, workspace_id=1) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_anonymous_release_does_not_free_an_owned_reservation(quota_pool: object) -> None:
    # Given only an owned delivery occupies the one available capacity slot.
    storage = PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    service = UsageService(storage)
    await service.set_quota(1, monthly_tts_requests=1)
    assert await service.reserve_owned(1, "tts", "delivery-a")

    # When a legacy, anonymous release is attempted without an anonymous reservation.
    await storage.cancel_reservation(1, "render")

    # Then the owned delivery retains its slot until it explicitly releases it.
    assert not await service.reserve_owned(1, "tts", "delivery-b")
    assert await service.cancel_owned("delivery-a")
    assert await service.reserve_owned(1, "tts", "delivery-b")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_cancelled_owner_cannot_record_late_usage(quota_pool: object) -> None:
    # Given a delivery whose reservation was cancelled while provider work was in flight.
    storage = PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    service = UsageService(storage)
    await service.set_quota(1, monthly_tts_requests=1)
    assert await service.reserve_owned(1, "tts", "delivery-a")
    assert await service.cancel_owned("delivery-a")

    # When late usage attempts to consume that cancelled reservation.
    with pytest.raises(ValueError, match="reservation owner"):
        await service.record_usage(
            1, 1, "edge_tts", "edge", "tts", idempotency_key="usage-a",
            reservation_owner_id="delivery-a",
        )

    # Then no unaccounted usage was persisted and new capacity is still available.
    assert await storage.list_by_run(1, workspace_id=1) == []
    assert await service.reserve_owned(1, "tts", "delivery-b")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_provider_wrapper_uses_separate_owner_and_event_keys(
    quota_pool: object, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an owned image reservation and an unrelated owned image reservation.
    storage = PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    service = UsageService(storage)
    monkeypatch.setattr(usage_module, "usage_service", service)
    await service.set_quota(1, monthly_image_generations=2)
    assert await service.reserve_owned(1, "image_gen", "delivery-a")
    assert await service.reserve_owned(1, "image_gen", "delivery-b")

    # When the first delivery reports a scene-specific usage event twice.
    for _ in range(2):
        await usage_module.record_provider_call(
            1, "image", "image-model", "image_gen", workspace_id=1,
            idempotency_key="delivery-a:scene-1", reservation_owner_id="delivery-a",
        )

    # Then only A's reservation is consumed; B retains its own slot.
    assert len(await storage.list_by_run(1, workspace_id=1)) == 1
    assert not await service.cancel_owned("delivery-a")
    assert await service.cancel_owned("delivery-b")


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_reservation_identity_is_explicit_for_owned_and_legacy_tasks(quota_pool: object) -> None:
    # Given an owned reservation and a legacy anonymous reservation.
    storage = PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    service = UsageService(storage)
    assert await service.reserve_owned(1, "tts", "owned-task")
    assert (await service.check_quota(1, "tts"))[0]

    # When the worker resolves each delivery's reservation ownership.
    owned = await service.reservation_owner_id("owned-task")
    legacy = await service.reservation_owner_id("legacy-task")

    # Then only the task with a real ledger entry is authorized as owner.
    assert owned == "owned-task"
    assert legacy is None


@pytest.mark.asyncio
@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_cancelled_reservation_is_not_authorized_as_worker_owner(quota_pool: object) -> None:
    # Given an owned task whose reservation was cancelled before delivery.
    storage = PostgresUsageStorage() if quota_pool is not None else InMemoryUsageStorage()
    service = UsageService(storage)
    assert await service.reserve_owned(1, "tts", "cancelled-delivery")
    assert await service.cancel_owned("cancelled-delivery")

    # When a late worker checks whether it may execute provider work.
    with pytest.raises(ValueError, match="Cancelled reservation owner"):
        await service.reservation_owner_id("cancelled-delivery")

    # Then cancelled ownership cannot masquerade as an anonymous legacy task.
    assert await service.reservation_owner_id("legacy-delivery") is None
