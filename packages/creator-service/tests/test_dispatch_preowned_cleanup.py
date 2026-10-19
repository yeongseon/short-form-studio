from decimal import Decimal

import pytest
from creator_domain.exceptions import ConflictError, ServiceUnavailableError
from creator_service import dispatch_cas
from creator_service.memory_task_tracking_storage import InMemoryTaskTrackingStorage
from creator_service.run_service import InMemoryRunStorage, RunService
from creator_service.task_dispatch_service import TaskDispatchService
from creator_service.task_tracking_service import TaskTrackingService
from creator_service.usage_service import InMemoryUsageStorage, UsageService

from .test_dispatch_port import RecordingDispatcher


async def _approved_render() -> tuple[RunService, UsageService, TaskDispatchService, int]:
    runs = RunService(InMemoryRunStorage())
    run = await runs.create_run(
        1, None, "default", current_stage="RENDER_GENERATING", workspace_id=1,
    )
    usage = UsageService(InMemoryUsageStorage())
    await usage.set_quota(1, monthly_cost_usd=Decimal("0.004"))
    assert await usage.reserve_owned(1, "render", "approved-render", Decimal("0.004"))
    return runs, usage, TaskDispatchService(RecordingDispatcher(queued=True)), run.id


async def _dispatch_preowned(
    runs: RunService, dispatch: TaskDispatchService, run_id: int,
) -> None:
    await dispatch.cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=frozenset({"RENDER_GENERATING"}),
        target_stage="RENDER_GENERATING",
        dispatcher=dispatch.dispatch_render_video,
        dispatcher_args={"run_id": run_id, "render_profile": "shorts_default"},
        run_service=runs,
        rollback_stage="TIMELINE_REVIEW",
        rollback_restart_from=None,
        enqueue_error_detail="enqueue failed",
        workspace_id=1,
        quota_operation_type="render",
        reservation_estimate_usd=Decimal("0.004"),
        reservation_owner_id="approved-render",
    )


@pytest.mark.asyncio
async def test_preowned_reservation_is_released_when_pre_run_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an approved render whose spend reservation has transferred to dispatch.
    runs, usage, dispatch, run_id = await _approved_render()
    monkeypatch.setattr("creator_service.usage_service.usage_service", usage)

    async def fail_read(*_args: object, **_kwargs: object) -> None:
        raise OSError("storage unavailable")

    monkeypatch.setattr(dispatch_cas, "read_run", fail_read)

    # When the pre-dispatch run lookup fails.
    with pytest.raises(ServiceUnavailableError):
        await _dispatch_preowned(runs, dispatch, run_id)

    # Then the reservation is released and approval is retryable.
    assert await usage.reserve_owned(1, "render", "replacement", Decimal("0.004"))
    run = await runs.get_run(run_id, workspace_id=1)
    assert run is not None and run.current_stage == "TIMELINE_REVIEW"


@pytest.mark.asyncio
async def test_preowned_reservation_is_released_when_quota_readmission_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an approved render whose spend reservation has transferred to dispatch.
    runs, usage, dispatch, run_id = await _approved_render()
    monkeypatch.setattr("creator_service.usage_service.usage_service", usage)

    async def fail_reserve(*_args: object, **_kwargs: object) -> None:
        raise ServiceUnavailableError("quota storage unavailable")

    monkeypatch.setattr(dispatch_cas, "reserve_quota", fail_reserve)

    # When readmission of the pre-owned reservation fails.
    with pytest.raises(ServiceUnavailableError):
        await _dispatch_preowned(runs, dispatch, run_id)

    # Then the reservation is released and approval is retryable.
    assert await usage.reserve_owned(1, "render", "replacement", Decimal("0.004"))
    run = await runs.get_run(run_id, workspace_id=1)
    assert run is not None and run.current_stage == "TIMELINE_REVIEW"


@pytest.mark.asyncio
async def test_preowned_reservation_is_released_when_run_is_cancelled_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given cancellation wins after approval but before the dispatch pre-check.
    runs, usage, dispatch, run_id = await _approved_render()
    monkeypatch.setattr("creator_service.usage_service.usage_service", usage)
    await runs.cancel_run(run_id, workspace_id=1)

    # When dispatch observes the cancellation.
    with pytest.raises(ConflictError):
        await _dispatch_preowned(runs, dispatch, run_id)

    # Then spend is released and the stage is restored without undoing cancellation.
    assert await usage.reserve_owned(1, "render", "replacement", Decimal("0.004"))
    run = await runs.get_run(run_id, workspace_id=1)
    assert run is not None and run.current_stage == "TIMELINE_REVIEW"
    assert run.status == "cancelled"


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement_phase", ["before_publish", "after_publish"])
async def test_dispatch_compensates_broker_replacement_around_publish(
    monkeypatch: pytest.MonkeyPatch, replacement_phase: str,
) -> None:
    # Given an approved dispatch whose broker generation changes around publish.
    runs, usage, dispatch, run_id = await _approved_render()
    generation = ["epoch-a"]
    published = False
    revoked: list[str] = []
    monkeypatch.setattr("creator_service.usage_service.usage_service", usage)
    monkeypatch.setattr(dispatch.dispatcher, "cancel", revoked.append)

    async def reserve(*_args: object, **_kwargs: object) -> int:
        return 1

    monkeypatch.setattr(dispatch_cas, "reserve_quota", reserve)

    def observe_generation() -> str:
        if replacement_phase == "after_publish" and published:
            generation[0] = "epoch-b"
        return generation[0]

    original_dispatch = dispatch.dispatch_render_video

    def publish(**kwargs: object) -> str:
        nonlocal published
        if replacement_phase == "before_publish":
            generation[0] = "epoch-b"
        result = original_dispatch(**kwargs)
        published = True
        return result

    publish.__name__ = "dispatch_render_video"
    monkeypatch.setattr(dispatch, "broker_generation", observe_generation)

    # When dispatch crosses the replacement boundary.
    with pytest.raises(ServiceUnavailableError):
        await dispatch.cas_dispatch_with_rollback(
            run_id=run_id,
            expected_stages=frozenset({"RENDER_GENERATING"}),
            target_stage="RENDER_GENERATING",
            dispatcher=publish,
            dispatcher_args={"run_id": run_id, "render_profile": "shorts_default"},
            run_service=runs,
            rollback_stage="TIMELINE_REVIEW",
            rollback_restart_from=None,
            enqueue_error_detail="enqueue failed",
            workspace_id=1,
            quota_operation_type="render",
            reservation_estimate_usd=Decimal("0.004"),
            reservation_owner_id="approved-render",
        )

    # Then the uncertain attempt is revoked and run/quota state is compensated.
    assert len(revoked) == 1
    assert await usage.reserve_owned(1, "render", "replacement", Decimal("0.004"))
    run = await runs.get_run(run_id, workspace_id=1)
    assert run is not None and run.current_stage == "TIMELINE_REVIEW"


@pytest.mark.asyncio
async def test_dispatch_compensates_when_post_publish_generation_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an approved dispatch that publishes before broker observation fails.
    runs, usage, dispatch, run_id = await _approved_render()
    tracking = TaskTrackingService(InMemoryTaskTrackingStorage())
    observations = 0
    monkeypatch.setattr("creator_service.usage_service.usage_service", usage)
    monkeypatch.setattr(
        "creator_service.task_tracking_service.task_tracking_service", tracking
    )

    async def reserve(*_args: object, **_kwargs: object) -> int:
        return 1

    def observe_generation() -> str:
        nonlocal observations
        observations += 1
        if observations == 2:
            raise ConnectionError("broker unavailable after publish")
        return "epoch-a"

    monkeypatch.setattr(dispatch_cas, "reserve_quota", reserve)
    monkeypatch.setattr(dispatch, "broker_generation", observe_generation)

    # When the post-publish generation read raises.
    with pytest.raises(ServiceUnavailableError):
        await _dispatch_preowned(runs, dispatch, run_id)

    # Then the uncertain attempt is revoked, terminalized, and compensated.
    task_id = dispatch.dispatcher.submissions[0].task_id
    assert task_id is not None
    task = await tracking.storage.get_by_celery_id(task_id)
    assert dispatch.dispatcher.cancelled == [task_id]
    assert task is not None and task["status"] == "revoked"
    assert await usage.reserve_owned(1, "render", "replacement", Decimal("0.004"))
    run = await runs.get_run(run_id, workspace_id=1)
    assert run is not None and run.current_stage == "TIMELINE_REVIEW"
