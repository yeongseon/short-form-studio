from __future__ import annotations

import inspect
from pathlib import Path

import celery
import yaml
from celery.concurrency.solo import TaskPool


ROOT = Path(__file__).parents[3]
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
WORKER_DOCKERFILE = ROOT / "apps" / "worker-orchestrator" / "Dockerfile"


def _worker_command(compose: str, service: str) -> list[str]:
    document = yaml.safe_load((ROOT / compose).read_text(encoding="utf-8"))
    return document["services"][service]["command"]


def test_default_worker_command_tracks_shipped_solo_topology() -> None:
    # Given the base deployment definition.
    command = _worker_command("docker-compose.yml", "worker")

    # When the process-test harness selects its worker arguments.
    worker_args = command[:]

    # Then it uses the exact shipped application, pool, and concurrency.
    assert worker_args == [
        "celery", "-A", "celery_app.celery_app", "worker", "--loglevel=info",
        "--pool=solo", "--concurrency=1",
    ]


def test_scaled_worker_commands_track_every_shipped_pool() -> None:
    # Given the queue-specific deployment definition.
    services = {
        name: _worker_command("docker-compose.scaled-workers.yml", name)
        for name in ("worker-script", "worker-image", "worker-audio", "worker-render")
    }

    # When their executable commands are inspected.
    pools = {name: next(arg for arg in command if arg.startswith("--pool=")) for name, command in services.items()}

    # Then process tests cover both the solo and prefork topologies actually shipped.
    assert pools == {
        "worker-script": "--pool=solo",
        "worker-image": "--pool=prefork",
        "worker-audio": "--pool=solo",
        "worker-render": "--pool=solo",
    }


def test_pinned_celery_solo_pool_declares_no_timeout_support() -> None:
    # Given the Celery version pinned by constraints.txt.
    pinned = next(
        line.removeprefix("celery==")
        for line in (ROOT / "constraints.txt").read_text(encoding="utf-8").splitlines()
        if line.startswith("celery==")
    )

    # When the installed solo implementation reports its capabilities.
    pool = TaskPool()

    # Then source and runtime evidence agree that execution is inline and untimed.
    assert celery.__version__ == pinned
    assert pool.info["timeouts"] == ()
    assert "self.on_apply = apply_target" in inspect.getsource(TaskPool.__init__)


def test_runtime_probe_is_shipped_and_registered_with_the_production_app() -> None:
    # Given the production Celery app imported exactly as the image imports it.
    from celery_app import celery_app

    # When its normal include list is loaded, without a test-only --include override.
    celery_app.loader.import_task_module("tasks.runtime_topology_probe")

    # Then the shipped probe traverses the production task runner.
    assert "runtime_topology.probe" in celery_app.tasks
    assert "tasks.runtime_topology_probe" in celery_app.conf.include
    assert "tasks.revoked_quota" in celery_app.conf.include


def test_runtime_ci_builds_and_runs_the_shipped_worker_image() -> None:
    # Given the worker topology CI job.
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    # When its runtime setup is inspected.
    dockerfile = str(WORKER_DOCKERFILE.relative_to(ROOT))

    # Then it builds the shipped Dockerfile and runs the image's own entrypoint/CMD.
    assert f"docker build --target runtime -f {dockerfile}" in workflow
    assert "docker run" in workflow
    assert "--entrypoint" not in workflow
    assert "docker image inspect worker-topology-image" in workflow


def test_runtime_ci_uses_postgres_redis_ffmpeg_and_uploads_complete_evidence() -> None:
    # Given the worker topology CI job definition.
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    # When service and artifact wiring are inspected.
    required = (
        "postgres:16.6-alpine",
        "redis:7.4-alpine",
        "ffmpeg -version",
        "manifest.json",
        "worker.log",
        "image-digest.txt",
        "resolved-command.txt",
    )

    # Then the real dependencies and diagnostic evidence are mandatory.
    for marker in required:
        assert marker in workflow
