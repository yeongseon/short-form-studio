"""Deterministic cancellation through the real synchronous task and async runner."""

from collections.abc import Awaitable, Callable, Coroutine

import anyio
import pytest
from tasks import task_runner
from worker_loop import run_in_worker_loop

from .scene_cancellation_support import SceneCase, scene_case as scene_case
from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import runner_case as runner_case


def with_controller(monkeypatch: pytest.MonkeyPatch, controller: Callable[[], Awaitable[None]]) -> None:
    """Run the real runner coroutine and a race controller on the same worker loop."""
    original = task_runner.run_in_worker_loop

    def controlled(coro: Coroutine):
        async def scenario():
            with anyio.fail_after(10):
                async with anyio.create_task_group() as group:
                    group.start_soon(controller)
                    return await coro
        return original(scenario())

    monkeypatch.setattr(task_runner, "run_in_worker_loop", controlled)


@pytest.mark.parametrize("blocked_index", [0, 1])
def test_cancel_during_provider_preserves_only_accepted_assets(
    scene_case: SceneCase, monkeypatch: pytest.MonkeyPatch, blocked_index: int,
) -> None:
    # Given scene0 or scene1 is blocked in the provider, after any earlier asset commits.
    case = scene_case
    case.provider.blocked_index = blocked_index

    async def cancel() -> None:
        await case.provider.entered.wait()
        await case.cancel()
        case.provider.released.set()

    with_controller(monkeypatch, cancel)
    # When cancellation wins before that in-flight provider returns.
    result = case.invoke()
    # Then no next provider or unaccepted asset is created; partial results match storage.
    assert case.provider.calls == [f"shot-{i}" for i in range(blocked_index + 1)]
    assets = run_in_worker_loop(case.assets.storage.list_assets_by_run(case.runner.run_id))
    assert len(assets) == blocked_index
    assert result["status"] == "cancelled"
    assert result["succeeded"] == blocked_index
    assert result["failed"] == 0
    assert len(result["scene_results"]) == blocked_index
    run = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (run["status"], run["current_stage"], run["version"]) == (
        "cancelled", "VISUAL_ASSET_GENERATING", 2,
    )
    task = run_in_worker_loop(case.runner.tracking.storage.get_by_celery_id(case.task_id))
    assert task["status"] == "revoked"
    for asset in assets:
        assert case.provider.paths[0].read_bytes() == b"generated-image"
        assert asset["is_active"] is True
    assert not case.provider.paths[-1].exists()


def test_normal_batch_keeps_multiple_images(scene_case: SceneCase) -> None:
    # Given a responsive provider and two scenes.
    scene_case.provider.released.set()
    # When the real task completes normally.
    result = scene_case.invoke()
    # Then both assets are accepted and the stage advances exactly once.
    assert (result["status"], result["succeeded"], result["failed"]) == ("success", 2, 0)
    assert scene_case.provider.calls == ["shot-0", "shot-1"]
    assets = run_in_worker_loop(scene_case.assets.storage.list_assets_by_run(scene_case.runner.run_id))
    assert len(assets) == 2
    assert all(path.read_bytes() == b"generated-image" for path in scene_case.provider.paths)
