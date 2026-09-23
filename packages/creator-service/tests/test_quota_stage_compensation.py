from unittest.mock import AsyncMock

import pytest
from creator_domain.exceptions import ConflictError, ServiceError, ServiceUnavailableError
from creator_domain.models import RunTask

from .quota_dispatch_support import QuotaDispatch, quota_dispatch, quota_pool  # noqa: F401

pytestmark = [pytest.mark.asyncio, pytest.mark.parametrize("quota_pool", ["memory", "postgres"], indirect=True)]


@pytest.mark.parametrize("typed", [False, True])
async def test_capacity_restored_when_stage_storage_raises(
    quota_dispatch: QuotaDispatch, monkeypatch: pytest.MonkeyPatch, typed: bool,
) -> None:
    # Given a real one-slot quota and a storage failure after reservation.
    case = quota_dispatch
    original = ServiceError("stage unavailable") if typed else OSError("private-storage-token")
    before = await case.runs.get_run(case.run_id, workspace_id=1)
    cancel = AsyncMock(wraps=case.usage.storage.cancel_reservation)
    monkeypatch.setattr(case.usage.storage, "cancel_reservation", cancel)
    monkeypatch.setattr(case.runs.storage, "conditional_update_run", AsyncMock(side_effect=original))
    # When dispatch cannot advance the stage.
    with pytest.raises(ServiceError) as caught:
        await case.dispatch()
    # Then exactly its reservation is returned without enqueueing or changing the run.
    assert (await case.usage.check_quota(1, "render"))[0] is True
    assert (await case.usage.check_quota(1, "render"))[0] is False
    cancel.assert_awaited_once_with(1, "render", units=1)
    assert case.port.submissions == []
    assert await case.tracking.list_run_tasks(case.run_id) == []
    assert await case.runs.get_run(case.run_id, workspace_id=1) == before
    if typed:
        assert caught.value is original
    else:
        assert type(caught.value) is ServiceUnavailableError
        assert str(caught.value) == "Storage failure during dispatch stage update"
        assert caught.value.__suppress_context__ is True


@pytest.mark.parametrize("release_applied", [False, True])
async def test_cleanup_failure_preserves_primary_error_without_secrets_or_retry(
    quota_dispatch: QuotaDispatch, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    release_applied: bool,
) -> None:
    # Given another reservation and an ambiguous cleanup acknowledgement.
    case = quota_dispatch
    await case.usage.set_quota(1, monthly_tts_requests=2)
    assert (await case.usage.check_quota(1, "render"))[0]
    original = ServiceError("primary-stage-token")
    cancel = case.usage.storage.cancel_reservation
    calls: list[int] = []

    async def fail_cancel(workspace_id: int, operation_type: str, units: int = 1) -> None:
        calls.append(units)
        if release_applied:
            await cancel(workspace_id, operation_type, units)
        raise OSError("postgresql://user:cleanup-secret@host/db")

    monkeypatch.setattr(case.usage.storage, "cancel_reservation", fail_cancel)
    monkeypatch.setattr(case.runs.storage, "conditional_update_run", AsyncMock(side_effect=original))
    # When both stage storage and cleanup fail.
    with pytest.raises(ServiceError) as caught:
        await case.dispatch()
    # Then cleanup is attempted once, never retried against somebody else's slot.
    assert caught.value is original
    assert calls == [1]
    assert (await case.usage.check_quota(1, "render"))[0] is release_applied
    assert (await case.usage.check_quota(1, "render"))[0] is False
    assert case.port.submissions == []
    assert "cleanup-secret" not in caplog.text
    assert "primary-stage-token" not in caplog.text
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info is None


@pytest.mark.parametrize("outcome", ["success", "cas_miss", "enqueue", "promotion", "cancel"])
async def test_existing_dispatch_paths_keep_quota_ownership(
    quota_dispatch: QuotaDispatch, monkeypatch: pytest.MonkeyPatch, outcome: str,
) -> None:
    # Given real quota with another owner's outstanding reservation.
    case = quota_dispatch
    await case.usage.set_quota(1, monthly_tts_requests=2)
    assert (await case.usage.check_quota(1, "render"))[0]
    cancel = AsyncMock(wraps=case.usage.storage.cancel_reservation)
    monkeypatch.setattr(case.usage.storage, "cancel_reservation", cancel)
    if outcome == "enqueue":
        from unittest.mock import Mock
        monkeypatch.setattr(case.port, "dispatch", Mock(side_effect=OSError("broker unavailable")))
    if outcome == "promotion":
        monkeypatch.setattr(case.tracking, "promote_pending_to_queued", AsyncMock(side_effect=OSError("promotion failed")))
    if outcome == "cancel":
        promote = case.tracking.promote_pending_to_queued

        async def cancel_during_promotion(task_id: str) -> RunTask | None:
            await case.runs.cancel_run(case.run_id, workspace_id=1)
            return await promote(task_id)

        monkeypatch.setattr(case.tracking, "promote_pending_to_queued", cancel_during_promotion)
    # When dispatch succeeds or takes an already-compensated failure branch.
    if outcome == "success":
        await case.dispatch()
    else:
        with pytest.raises(ConflictError if outcome in {"cas_miss", "cancel"} else ServiceUnavailableError):
            await case.dispatch("IDEA_READY" if outcome == "cas_miss" else "SUBTITLE_GENERATING")
    # Then successful dispatch retains its slot; failures return only one slot.
    assert cancel.await_count == (0 if outcome == "success" else 1)
    assert (await case.usage.check_quota(1, "render"))[0] is (outcome != "success")
    assert (await case.usage.check_quota(1, "render"))[0] is False
    run = await case.runs.get_run(case.run_id, workspace_id=1)
    assert run is not None
    assert run.current_stage == ("RENDER_GENERATING" if outcome == "success" else "SUBTITLE_GENERATING")
    assert run.status == ("cancelled" if outcome == "cancel" else "pending")


async def test_dispatch_can_retry_after_stage_failure(
    quota_dispatch: QuotaDispatch, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a previous dispatch failed before changing the run stage.
    case = quota_dispatch
    with monkeypatch.context() as patch:
        patch.setattr(case.runs.storage, "conditional_update_run", AsyncMock(side_effect=OSError("storage unavailable")))
        with pytest.raises(ServiceUnavailableError):
            await case.dispatch()
    # When storage recovers and the same run is dispatched again.
    result = await case.dispatch()
    # Then only the successful attempt is queued and retains the single quota slot.
    assert result["current_stage"] == "RENDER_GENERATING"
    assert len(case.port.submissions) == 1
    assert (await case.usage.check_quota(1, "render"))[0] is False
