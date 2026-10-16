from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Literal, assert_never
from urllib.parse import urlsplit
from urllib.request import urlopen

from celery import Task
from celery_app import celery_app
from celery.worker.request import Request
from creator_domain.models.stage import RunStage
from creator_service.run_service import run_service
from tasks.hard_timeout import finalize_hard_timeout
from tasks.task_runner import TaskContext, TaskResult, TaskRunnerConfig, run_task

type ProbeMode = Literal["complete", "cooperative", "ffmpeg_hang", "redelivery", "wait"]


def _evidence_file(name: str) -> Path:
    root = Path(os.environ["WORKER_TOPOLOGY_EVIDENCE_DIR"]).resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root:
        raise ValueError("Invalid topology evidence path")
    return candidate


def _provider_url(candidate: str) -> str:
    configured = os.environ["WORKER_TOPOLOGY_PROVIDER_URL"].rstrip("/")
    if urlsplit(candidate) != urlsplit(configured):
        raise ValueError("Invalid topology provider URL")
    return configured


class _TopologyRequest(Request):
    def on_timeout(self, soft: bool, timeout: float) -> None:
        super().on_timeout(soft, timeout)
        if soft or not isinstance(self.id, str) or not self.args:
            return
        run_id = self.args[0]
        if isinstance(run_id, int):
            finalize_hard_timeout(self.id, run_id, timeout)


class _TopologyTask(Task):
    Request = _TopologyRequest


def _publish(path: str, status: str, **fields: str | int | float | bool) -> None:
    destination = _evidence_file(path)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps({"status": status, **fields}), encoding="utf-8")
    temporary.replace(destination)


@celery_app.task(bind=True, base=_TopologyTask, name="runtime_topology.probe", acks_late=True)
def runtime_topology_probe(
    self: Task,
    run_id: int,
    mode: ProbeMode,
    evidence_path: str,
    provider_url: str = "",
) -> dict[str, object]:
    config = TaskRunnerConfig(
        task_name="runtime_topology_probe",
        allowed_stages=frozenset({RunStage.RENDER_GENERATING}),
        safe_stages=frozenset({RunStage.RENDER_GENERATING.value}),
    )

    async def execute(ctx: TaskContext) -> TaskResult:
        match mode:
            case "complete":
                _publish(evidence_path, "completed", task_id=ctx.task_id)
            case "cooperative":
                with urlopen(f"{_provider_url(provider_url)}/provider", timeout=5) as response:
                    response.read()
                _publish(evidence_path, "provider_done", task_id=ctx.task_id)
                while True:
                    current = await run_service.storage.get_run(run_id)
                    if current is not None and current.get("status") == "cancelled":
                        from creator_service.usage_service import usage_service

                        await usage_service.cancel_owned(ctx.task_id)
                        _publish(
                            evidence_path,
                            "cancelled",
                            task_id=ctx.task_id,
                            second_boundary_suppressed=True,
                        )
                        return TaskResult(status="cancelled")
                    time.sleep(0.05)
            case "ffmpeg_hang":
                child = subprocess.Popen(
                    [
                        "ffmpeg", "-nostdin", "-f", "lavfi", "-i",
                        "testsrc=size=64x64:rate=30", "-f", "null", "-",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                _publish(evidence_path, "ffmpeg_running", task_id=ctx.task_id, child_pid=child.pid)
                try:
                    child.wait()
                finally:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait(timeout=5)
            case "wait":
                _publish(evidence_path, "running", task_id=ctx.task_id)
                while True:
                    time.sleep(0.1)
            case "redelivery":
                state = _evidence_file(evidence_path)
                if state.exists():
                    _publish(evidence_path, "redelivered", task_id=ctx.task_id)
                    while True:
                        current = await run_service.storage.get_run(run_id)
                        if current is not None and current.get("status") == "cancelled":
                            _publish(evidence_path, "cancelled", task_id=ctx.task_id)
                            return TaskResult(status="cancelled")
                        time.sleep(0.05)
                _publish(evidence_path, "claimed", task_id=ctx.task_id)
                while True:
                    time.sleep(0.1)
            case unreachable:
                assert_never(unreachable)
        return TaskResult()

    return run_task(self, run_id, config, execute)
