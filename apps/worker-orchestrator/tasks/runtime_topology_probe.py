from __future__ import annotations

import json
import os
import signal
import subprocess
from pathlib import Path
from typing import Literal, assert_never
from urllib.parse import urlsplit
from urllib.request import urlopen

import anyio
from celery import Task
from celery_app import celery_app
from celery.worker.request import Request
from creator_domain.models.stage import RunStage
from creator_service.run_service import run_service
from tasks.hard_timeout import finalize_hard_timeout
from tasks.task_runner import TaskContext, TaskResult, TaskRunnerConfig, run_task

type ProbeMode = Literal[
    "cancellation_gate", "complete", "ffmpeg_hang", "redelivery",
    "timeout_resources", "wait"
]


def _evidence_file(name: str) -> Path:
    root = Path(os.environ["WORKER_TOPOLOGY_EVIDENCE_DIR"]).resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or candidate == root:
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
        claim_token = (
            f"{self.id}:{self.worker_pid}" if isinstance(self.worker_pid, int) else None
        )
        if isinstance(run_id, int) and claim_token is not None:
            finalize_hard_timeout(self.id, claim_token, run_id, timeout)
            if self.args[1] == "timeout_resources" and isinstance(self.args[2], str):
                state = json.loads(_evidence_file(self.args[2]).read_text(encoding="utf-8"))
                child_pid = state.get("child_pid")
                temporary_path = state.get("temporary_path")
                if isinstance(child_pid, int):
                    os.killpg(child_pid, signal.SIGKILL)
                if isinstance(temporary_path, str):
                    _evidence_file(temporary_path).unlink(missing_ok=True)


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
    self.request.claim_token = f"{self.request.id}:{os.getpid()}"
    config = TaskRunnerConfig(
        task_name="runtime_topology_probe",
        allowed_stages=frozenset({RunStage.RENDER_GENERATING}),
        safe_stages=frozenset({RunStage.RENDER_GENERATING.value}),
    )

    async def execute(ctx: TaskContext) -> TaskResult:
        match mode:
            case "cancellation_gate":
                from creator_service.render_service import render_service

                with urlopen(f"{_provider_url(provider_url)}/provider", timeout=5) as response:
                    response.read()
                _publish(evidence_path, "provider_done", task_id=ctx.task_id)
                continue_marker = _evidence_file(evidence_path).with_suffix(".continue")
                while not continue_marker.exists():
                    current = await run_service.storage.get_run(run_id)
                    if current is not None and current.get("status") == "cancelled":
                        from creator_service.usage_service import usage_service

                        await usage_service.cancel_owned(ctx.task_id)
                        _publish(evidence_path, "cancelled", task_id=ctx.task_id)
                        return TaskResult(status="cancelled")
                    await anyio.sleep(0.05)
                with urlopen(f"{_provider_url(provider_url)}/provider", timeout=5) as response:
                    response.read()
                storage = _evidence_file(f"storage/{run_id}/artifact.bin")
                storage.parent.mkdir(parents=True, exist_ok=True)
                storage.write_bytes(b"topology-artifact")
                await render_service.create_artifact(
                    run_id,
                    str(storage),
                    storage_provider="local",
                    storage_key=str(storage.relative_to(_evidence_file("storage"))),
                    idempotency_key=ctx.task_id,
                )
                _publish(evidence_path, "boundaries_completed", task_id=ctx.task_id)
            case "complete":
                _publish(evidence_path, "completed", task_id=ctx.task_id)
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
                    await anyio.sleep(0.1)
            case "redelivery":
                state = _evidence_file(evidence_path)
                if state.exists():
                    _publish(
                        evidence_path,
                        "redelivered",
                        task_id=ctx.task_id,
                        worker_pid=os.getpid(),
                    )
                    cancel_marker = state.with_suffix(".cancel")
                    while not cancel_marker.exists():
                        current = await run_service.storage.get_run(run_id)
                        if current is not None and current.get("status") == "cancelled":
                            _publish(evidence_path, "cancelled", task_id=ctx.task_id)
                            return TaskResult(status="cancelled")
                        await anyio.sleep(0.05)
                    _publish(evidence_path, "cancelled", task_id=ctx.task_id)
                    return TaskResult(status="cancelled")
                _publish(
                    evidence_path,
                    "claimed",
                    task_id=ctx.task_id,
                    worker_pid=os.getpid(),
                )
                kill_marker = state.with_suffix(".kill")
                while not kill_marker.exists():
                    await anyio.sleep(0.05)
                os.kill(os.getpid(), signal.SIGKILL)
            case "timeout_resources":
                temporary = _evidence_file(f"storage/{run_id}/timeout.tmp")
                temporary.parent.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(b"timeout-owned")
                child = subprocess.Popen(
                    ["python3", "-c", "import time; time.sleep(300)"],
                    start_new_session=True,
                )
                _publish(
                    evidence_path,
                    "resources_active",
                    task_id=ctx.task_id,
                    child_pid=child.pid,
                    temporary_path=str(temporary.relative_to(_evidence_file("storage").parent)),
                )
                child.wait()
            case unreachable:
                assert_never(unreachable)
        return TaskResult()

    return run_task(self, run_id, config, execute)
