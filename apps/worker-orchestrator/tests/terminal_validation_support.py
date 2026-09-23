"""Real storage-backed runner fixture shared by terminal-policy scenarios."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from creator_domain.models.stage import RunStage
from creator_service.postgres_run_storage import PostgresRunStorage
from creator_service.postgres_task_tracking_storage import PostgresTaskTrackingStorage
from creator_service.run_service import InMemoryRunStorage, RunService
from creator_service.task_tracking_service import InMemoryTaskTrackingStorage, TaskTrackingService
from tasks import task_runner
from worker_loop import run_in_worker_loop

from .terminal_postgres_support import terminal_pool as terminal_pool


@dataclass(frozen=True, slots=True)
class RunnerCase:
    runs: RunService
    tracking: TaskTrackingService
    run_id: int
    config: task_runner.TaskRunnerConfig

    def delivery(self, retries: int = 0) -> SimpleNamespace:
        return SimpleNamespace(
            request=SimpleNamespace(id="validation-task", args=(), kwargs={}, retries=retries),
            max_retries=2,
        )


@pytest.fixture(params=["memory", "postgres"])
def runner_case(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> RunnerCase:
    postgres = request.param == "postgres"
    if postgres:
        request.getfixturevalue("terminal_pool")
    runs = RunService(PostgresRunStorage() if postgres else InMemoryRunStorage())
    tracking = TaskTrackingService(PostgresTaskTrackingStorage() if postgres else InMemoryTaskTrackingStorage())
    monkeypatch.setattr(task_runner, "_run_service", runs)
    monkeypatch.setattr(task_runner, "_task_tracking_service", tracking)

    async def workspace(_run_id: int) -> int:
        return 1

    monkeypatch.setattr(task_runner, "resolve_workspace_id_from_run", workspace)
    row = run_in_worker_loop(runs.storage.create_run({
        "project_id": 1, "workspace_id": 1,
        "current_stage": "SCRIPT_GENERATING", "status": "running",
    }))
    return RunnerCase(runs, tracking, row["id"], task_runner.TaskRunnerConfig(
        task_name="generate_script",
        allowed_stages=frozenset({RunStage.SCRIPT_GENERATING}),
        safe_stages=frozenset({"SCRIPT_GENERATING"}),
        success_stage="SCRIPT_REVIEW",
    ))
