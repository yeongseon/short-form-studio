from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import anyio
import pytest
from tasks import generate_scene_image, hard_timeout


@dataclass(frozen=True, slots=True)
class _Asset:
    asset_path: str


class _AssetService:
    def __init__(self, persisted: set[Path]) -> None:
        self._persisted = persisted

    async def list_by_run(self, _run_id: int) -> dict[str, list[_Asset]]:
        return {"scene": [_Asset(str(path)) for path in self._persisted]}


def _run(coroutine):
    async def await_coroutine():
        return await coroutine

    return anyio.run(await_coroutine)


def test_stale_timeout_cleanup_preserves_successor_delivery_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given deliveries share a task id and PID across distinct worker replicas.
    run_id = 864
    task_id = "shared-delivery"
    worker_pid = 111
    old_hostname = "worker-image@replica-1"
    successor_hostname = "worker-image@replica-2"
    old_claim_token = hard_timeout.delivery_owner(task_id, old_hostname, worker_pid)
    successor_claim_token = hard_timeout.delivery_owner(
        task_id,
        successor_hostname,
        worker_pid,
    )
    scene_dir = tmp_path / str(run_id) / "scenes"
    scene_dir.mkdir(parents=True)
    old_output = scene_dir / f"scene-{old_claim_token}-old.png"
    successor_output = scene_dir / f"scene-{successor_claim_token}-successor.png"
    old_output.touch()
    successor_output.touch()
    monkeypatch.setattr(generate_scene_image, "_ARTIFACTS_BASE", str(tmp_path))
    monkeypatch.setattr(generate_scene_image, "_visual_asset_service", _AssetService(set()))
    monkeypatch.setattr("worker_loop.run_in_worker_loop", _run)

    # When the stale parent cleans only the timed-out delivery's outputs.
    generate_scene_image._cleanup_hard_timeout_outputs(
        run_id,
        task_id,
        old_hostname,
        worker_pid,
    )

    # Then the old output is removed without unlinking the successor's output.
    assert old_claim_token != successor_claim_token
    assert not old_output.exists()
    assert successor_output.exists()


def test_hard_timeout_cleanup_preserves_persisted_scene_and_removes_unfinished_scene(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given one persisted and one unfinished output owned by the timed-out delivery.
    run_id = 865
    task_id = "two-scene-delivery"
    worker_hostname = "worker-image@replica-1"
    worker_pid = 333
    owner = hard_timeout.delivery_owner(task_id, worker_hostname, worker_pid)
    scene_dir = tmp_path / str(run_id) / "scenes"
    scene_dir.mkdir(parents=True)
    persisted = scene_dir / f"scene-1-{owner}-persisted.png"
    unfinished = scene_dir / f"scene-2-{owner}-unfinished.png"
    persisted.touch()
    unfinished.touch()
    monkeypatch.setattr(generate_scene_image, "_ARTIFACTS_BASE", str(tmp_path))
    monkeypatch.setattr(
        generate_scene_image,
        "_visual_asset_service",
        _AssetService({persisted}),
    )
    monkeypatch.setattr("worker_loop.run_in_worker_loop", _run)

    # When hard-timeout cleanup runs for that delivery.
    generate_scene_image._cleanup_hard_timeout_outputs(
        run_id,
        task_id,
        worker_hostname,
        worker_pid,
    )

    # Then persisted-path protection remains while unfinished output is removed.
    assert persisted.exists()
    assert not unfinished.exists()
