"""TDD tests for PR 6: asset_versions surfaced in task_runner result dict."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from creator_domain.models.stage import RunStage
from creator_provider.versioned_assets import (
    _loaded_assets_ctx,
    get_loaded_asset_versions,
)
from tasks.task_runner import TaskContext, TaskResult, TaskRunnerConfig, _run_task_inner

_DUMMY_CONFIG = TaskRunnerConfig(
    task_name="generate_script",
    allowed_stages=frozenset({RunStage.IDEA_READY}),
    safe_stages=frozenset({"IDEA_READY"}),
)


def _make_run(stage: str = "IDEA_READY") -> dict[str, Any]:
    return {"id": 1, "current_stage": stage, "workspace_id": 1, "project_id": 1}


def _stub_services(monkeypatch: pytest.MonkeyPatch, run: dict | None = None) -> None:
    if run is None:
        run = _make_run()

    tracking = MagicMock()
    tracking.storage.get_by_celery_id = AsyncMock(return_value=None)
    tracking.record_task_start = AsyncMock(return_value=SimpleNamespace(status="running"))
    tracking.mark_success = AsyncMock()
    tracking.mark_failed = AsyncMock()
    monkeypatch.setattr("tasks.task_runner._task_tracking_service", tracking)

    run_svc = MagicMock()
    run_svc.storage.get_run = AsyncMock(return_value=run)
    monkeypatch.setattr("tasks.task_runner._run_service", run_svc)

    monkeypatch.setattr("tasks.task_runner.resolve_workspace_id_from_run", AsyncMock(return_value=1))
    monkeypatch.setattr("tasks.task_runner.acquire_gpu_lock", AsyncMock(return_value=True))
    monkeypatch.setattr("tasks.task_runner.release_gpu_lock", AsyncMock())
    monkeypatch.setattr("tasks.task_runner.renew_gpu_lock", AsyncMock())
    monkeypatch.setattr("celery_app.is_shutting_down", lambda: False)
    monkeypatch.setattr("tasks.task_runner._run_service.advance_stage", AsyncMock())


def _set_asset_versions(versions: dict[str, str]) -> None:
    _loaded_assets_ctx.set(versions)


@pytest.mark.asyncio
async def test_result_includes_asset_versions_from_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_services(monkeypatch)

    async def _execute(ctx: TaskContext) -> TaskResult:
        _set_asset_versions({"prompts/script_gen": "v2.1", "schemas/output": "v1.0"})
        return TaskResult(status="success")

    result = await _run_task_inner(run_id=1, task_id="test-asset-1", config=_DUMMY_CONFIG, execute=_execute)
    assert "asset_versions" in result
    assert result["asset_versions"] == {"prompts/script_gen": "v2.1", "schemas/output": "v1.0"}


@pytest.mark.asyncio
async def test_result_asset_versions_empty_when_no_assets_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_services(monkeypatch)

    async def _execute(ctx: TaskContext) -> TaskResult:
        return TaskResult(status="success")

    result = await _run_task_inner(run_id=1, task_id="test-asset-2", config=_DUMMY_CONFIG, execute=_execute)
    assert "asset_versions" in result
    assert result["asset_versions"] == {}


@pytest.mark.asyncio
async def test_asset_versions_isolated_between_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_services(monkeypatch)

    # Pollute ContextVar before the task runs
    _set_asset_versions({"prompts/leaked": "v0.1"})

    async def _execute(ctx: TaskContext) -> TaskResult:
        _set_asset_versions({**get_loaded_asset_versions(), "prompts/fresh": "v1.0"})
        return TaskResult(status="success")

    result = await _run_task_inner(run_id=1, task_id="test-asset-3", config=_DUMMY_CONFIG, execute=_execute)
    assert "prompts/leaked" not in result["asset_versions"]
    assert result["asset_versions"] == {"prompts/fresh": "v1.0"}


@pytest.mark.asyncio
async def test_idempotent_skip_includes_empty_asset_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_services(monkeypatch)

    tracking = MagicMock()
    tracking.storage.get_by_celery_id = AsyncMock(return_value={
        "status": "success", "run_id": 1, "task_type": "generate_script",
    })
    tracking.record_task_start = AsyncMock()
    tracking.mark_success = AsyncMock()
    monkeypatch.setattr("tasks.task_runner._task_tracking_service", tracking)

    async def _never_execute(ctx: TaskContext) -> TaskResult:
        raise AssertionError("execute must not run for idempotent skip")

    result = await _run_task_inner(run_id=1, task_id="real-task-id", config=_DUMMY_CONFIG, execute=_never_execute)
    assert result["idempotent_skip"] is True
    assert result["asset_versions"] == {}


@pytest.mark.asyncio
async def test_asset_versions_present_on_failed_task(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_services(monkeypatch)

    async def _execute(ctx: TaskContext) -> TaskResult:
        _set_asset_versions({"tools/image_gen": "v3.0"})
        return TaskResult(status="failed", extra={"error": "some error"})

    result = await _run_task_inner(run_id=1, task_id="test-asset-fail", config=_DUMMY_CONFIG, execute=_execute)
    assert result["status"] == "failed"
    assert result["asset_versions"] == {"tools/image_gen": "v3.0"}


@pytest.mark.asyncio
async def test_extra_cannot_override_asset_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    """result.extra containing 'asset_versions' must not override the tracked versions."""
    _stub_services(monkeypatch)

    async def _execute(ctx: TaskContext) -> TaskResult:
        _set_asset_versions({"prompts/real": "v1.0"})
        return TaskResult(status="success", extra={"asset_versions": {"prompts/fake": "v9.9"}})

    result = await _run_task_inner(run_id=1, task_id="test-override", config=_DUMMY_CONFIG, execute=_execute)
    assert result["asset_versions"] == {"prompts/real": "v1.0"}
