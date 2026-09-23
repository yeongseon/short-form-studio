import anyio
import pytest
from creator_provider.exceptions import ProviderError
from tasks import generate_scene_image as images
from worker_loop import run_in_worker_loop

from .scene_cancellation_support import SceneCase, scene_case as scene_case
from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import runner_case as runner_case
from .test_scene_cancellation import with_controller


@pytest.mark.parametrize("retry", [True, False])
def test_cancellation_during_backoff_stops_retry_or_next_scene(
    scene_case: SceneCase, monkeypatch: pytest.MonkeyPatch, retry: bool,
) -> None:
    # Given a parse retry or an inter-scene delay in the real batch loop.
    case = scene_case
    case.provider.released.set()
    case.provider.error = ProviderError("invalid svg") if retry else None
    entered = anyio.Event()
    released = anyio.Event()
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        entered.set()
        await released.wait()

    async def cancel() -> None:
        await entered.wait()
        await case.cancel()
        released.set()

    monkeypatch.setattr(anyio, "sleep", sleep)
    with_controller(monkeypatch, cancel)
    # When cancellation arrives while sleeping, without cancelling an external call.
    result = case.invoke("groq-svg")
    # Then one bounded sleep is enough to observe cancellation and no provider follows.
    assert waits == [0.5]
    assert case.provider.calls == ["shot-0"]
    assert (result["status"], result["succeeded"], result["failed"]) == (
        "cancelled", 0 if retry else 1, 0,
    )


def test_cancel_after_provider_before_persistence(
    scene_case: SceneCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given provider completion followed by an awaited usage record before persistence.
    case = scene_case
    case.provider.released.set()

    async def usage(*args: int, **kwargs: str) -> None:
        await case.cancel()

    monkeypatch.setattr(images, "record_provider_call", usage)
    # When cancellation is committed at that await boundary.
    result = case.invoke()
    # Then the batch stops without persisting the returned image.
    assert result["status"] == "cancelled"
    assert result["succeeded"] == 0
    assert case.provider.calls == ["shot-0"]
    assert run_in_worker_loop(case.assets.storage.list_assets_by_run(case.runner.run_id)) == []


@pytest.mark.parametrize("provider_fails", [False, True])
def test_final_transition_sql_predicate_preserves_cancellation(
    scene_case: SceneCase, monkeypatch: pytest.MonkeyPatch, provider_fails: bool,
) -> None:
    # Given all scene work finished, but the real guarded storage write has not run.
    case = scene_case
    case.provider.released.set()
    case.provider.error = ProviderError("unavailable") if provider_fails else None
    original = case.runner.runs.storage.conditional_update_run

    async def cancel_before_cas(*args, **kwargs):
        await case.cancel()
        return await original(*args, **kwargs)

    monkeypatch.setattr(case.runner.runs.storage, "conditional_update_run", cancel_before_cas)
    # When cancellation wins immediately before the actual memory/SQL predicate.
    result = case.invoke()
    # Then neither successful nor failed batch completion overwrites it or its version.
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["status"], saved["current_stage"], saved["version"]) == (
        "cancelled", "VISUAL_ASSET_GENERATING", 2,
    )
    assert result["status"] == "cancelled"
    assert result["succeeded"] == (0 if provider_fails else 2)
    task = run_in_worker_loop(case.runner.tracking.storage.get_by_celery_id(case.task_id))
    assert task["status"] == "revoked"


def test_task_revocation_alone_stops_scene_batch(
    scene_case: SceneCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a live run whose task is revoked while scene0 is blocked.
    case = scene_case

    async def revoke() -> None:
        await case.provider.entered.wait()
        await case.runner.tracking.mark_revoked(case.task_id)
        case.provider.released.set()

    with_controller(monkeypatch, revoke)
    # When the surviving task returns from the external call.
    result = case.invoke()
    # Then revocation alone halts further work without a finished-stage write.
    assert result["status"] == "cancelled"
    assert case.provider.calls == ["shot-0"]
    assert run_in_worker_loop(case.assets.storage.list_assets_by_run(case.runner.run_id)) == []
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["status"], saved["current_stage"], saved["version"]) == (
        "running", "VISUAL_ASSET_GENERATING", 1,
    )


def test_cancel_after_asset_commit_keeps_result_consistent(
    scene_case: SceneCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an asset transaction that has accepted scene0 before cancellation.
    case = scene_case
    case.provider.released.set()
    original = case.assets.create_asset

    async def cancel_after_save(*args, **kwargs):
        asset = await original(*args, **kwargs)
        await case.cancel()
        return asset

    monkeypatch.setattr(case.assets, "create_asset", cancel_after_save)
    # When cancellation is observed after the completed persistence operation.
    result = case.invoke()
    # Then accepted media and its successful partial result remain, but scene1 never starts.
    assert (result["status"], result["succeeded"], result["failed"]) == ("cancelled", 1, 0)
    assert case.provider.calls == ["shot-0"]
    assert case.provider.paths[0].read_bytes() == b"generated-image"
    assert len(run_in_worker_loop(case.assets.storage.list_assets_by_run(case.runner.run_id))) == 1


@pytest.mark.parametrize("provider_fails", [False, True])
def test_final_transition_preserves_advanced_stage(
    scene_case: SceneCase, monkeypatch: pytest.MonkeyPatch, provider_fails: bool,
) -> None:
    case = scene_case
    case.provider.released.set()
    case.provider.error = ProviderError("unavailable") if provider_fails else None
    original = case.runner.runs.storage.conditional_update_run

    async def advance_before_cas(*args, **kwargs):
        await case.runner.runs.storage.update_run(case.runner.run_id, {
            "current_stage": "AUDIO_GENERATING",
        })
        return await original(*args, **kwargs)

    monkeypatch.setattr(case.runner.runs.storage, "conditional_update_run", advance_before_cas)
    case.invoke()
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["status"], saved["current_stage"], saved["version"]) == (
        "running", "AUDIO_GENERATING", 2,
    )
