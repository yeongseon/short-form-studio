from __future__ import annotations

import inspect
from pathlib import Path

import celery
import yaml
from celery.concurrency.solo import TaskPool


ROOT = Path(__file__).parents[3]


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


def test_topology_process_support_is_registered_for_real_worker_subprocesses() -> None:
    # Given the production Celery app imported exactly as Compose imports it.
    from celery_app import celery_app

    # When the opt-in process-test task module is requested.
    celery_app.loader.import_task_module("tests.worker_topology_tasks")

    # Then synthetic lifecycle tasks can be delivered through the real app.
    assert "worker_topology.cooperative" in celery_app.tasks
    assert "worker_topology.deadline" in celery_app.tasks
    assert "worker_topology.attempt" in celery_app.tasks
