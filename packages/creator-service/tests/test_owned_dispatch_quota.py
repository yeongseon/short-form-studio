import pytest
from creator_domain.exceptions import ServiceUnavailableError

from .quota_dispatch_support import QuotaDispatch, quota_dispatch, quota_pool  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_dispatched_task_owns_reservation_and_timeout_releases_only_it(
    quota_dispatch: QuotaDispatch,
) -> None:
    # Given one run and capacity for two independent reservations.
    case = quota_dispatch
    await case.usage.set_quota(1, monthly_tts_requests=2)
    assert await case.usage.reserve_owned(1, "tts", "other-delivery")

    # When a render task is dispatched and only its delivery expires.
    result = await case.dispatch()
    assert case.port.submissions[0].task_id == result["task_id"]
    assert await case.usage.cancel_owned(str(result["task_id"]))
    assert not await case.usage.cancel_owned(str(result["task_id"]))

    # Then the other delivery still holds one capacity unit.
    assert await case.usage.reserve_owned(1, "render", "replacement")
    assert not await case.usage.reserve_owned(1, "render", "extra")


@pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)
async def test_stage_failure_cancels_only_its_owned_reservation(
    quota_dispatch: QuotaDispatch, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an independent reservation and an exception after this dispatch reserves.
    case = quota_dispatch
    await case.usage.set_quota(1, monthly_tts_requests=2)
    assert await case.usage.reserve_owned(1, "tts", "other-delivery")

    async def fail_stage(*_args: object, **_kwargs: object) -> None:
        raise OSError("stage storage unavailable")

    monkeypatch.setattr(case.runs.storage, "conditional_update_run", fail_stage)
    # When the stage transition fails before enqueue.
    with pytest.raises(ServiceUnavailableError):
        await case.dispatch()

    # Then one new reservation fits and the unrelated one remains.
    assert await case.usage.reserve_owned(1, "render", "replacement")
    assert not await case.usage.reserve_owned(1, "render", "extra")
