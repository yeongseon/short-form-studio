from __future__ import annotations

import builtins
from types import SimpleNamespace

import pytest

from shorts_api.routes import creator_runs_utils


class _TrackingServiceStub:
    def __init__(self) -> None:
        self.marked: list[str] = []

    async def get_active_celery_ids(self, _run_id: int) -> list[str]:
        return ["ok-1", "fail-1", "ok-2"]

    async def revoke_active_tasks(self, _run_id: int) -> list[str]:
        return ["ok-1", "fail-1", "ok-2"]

    async def mark_tasks_revoked(self, celery_ids: list[str]) -> None:
        self.marked.extend(celery_ids)


class _TrackingServiceSingleStub:
    def __init__(self, ids: list[str] | Exception) -> None:
        self._ids = ids
        self.marked: list[str] = []

    async def get_active_celery_ids(self, _run_id: int) -> list[str]:
        if isinstance(self._ids, Exception):
            raise self._ids
        return self._ids

    async def mark_tasks_revoked(self, celery_ids: list[str]) -> None:
        self.marked.extend(celery_ids)


class _ControlStub:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def revoke(self, task_id: str, terminate: bool = False) -> None:
        self.calls.append(task_id)
        if task_id == "fail-1":
            raise RuntimeError("broker failure")


@pytest.mark.asyncio
async def test_revoke_active_tasks_marks_only_successful_broker_revokes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracking = _TrackingServiceStub()
    control = _ControlStub()
    celery_app = SimpleNamespace(control=control)

    monkeypatch.setattr(
        creator_runs_utils,
        "import_module",
        lambda _name: SimpleNamespace(task_tracking_service=tracking),
    )
    original_import = builtins.__import__

    def _import(name: str, *args, **kwargs):
        if name == "celery_app":
            return SimpleNamespace(celery_app=celery_app)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)

    await creator_runs_utils._revoke_active_tasks_for_run(42)

    assert control.calls == ["ok-1", "fail-1", "ok-2"]
    assert tracking.marked == ["ok-1", "ok-2"]


@pytest.mark.asyncio
async def test_collect_active_celery_ids_returns_tuple_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracking = _TrackingServiceSingleStub(["id-1"])
    monkeypatch.setattr(
        creator_runs_utils,
        "import_module",
        lambda _name: SimpleNamespace(task_tracking_service=tracking),
    )
    result = await creator_runs_utils._collect_active_celery_ids(1)
    assert result == (["id-1"], True)


@pytest.mark.asyncio
async def test_collect_active_celery_ids_returns_tuple_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracking = _TrackingServiceSingleStub(RuntimeError("db down"))
    monkeypatch.setattr(
        creator_runs_utils,
        "import_module",
        lambda _name: SimpleNamespace(task_tracking_service=tracking),
    )
    result = await creator_runs_utils._collect_active_celery_ids(1)
    assert result == ([], False)


@pytest.mark.asyncio
async def test_revoke_celery_ids_returns_true_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracking = _TrackingServiceSingleStub(["id-1", "id-2"])
    control = _ControlStub()
    celery_app = SimpleNamespace(control=control)

    monkeypatch.setattr(
        creator_runs_utils,
        "import_module",
        lambda _name: SimpleNamespace(task_tracking_service=tracking),
    )
    original_import = builtins.__import__

    def _import(name: str, *args, **kwargs):
        if name == "celery_app":
            return SimpleNamespace(celery_app=celery_app)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    result = await creator_runs_utils._revoke_celery_ids(["id-1", "id-2"], 1)
    assert result is True


@pytest.mark.asyncio
async def test_revoke_celery_ids_returns_false_on_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracking = _TrackingServiceSingleStub(["ok-1", "fail-1", "ok-2"])
    control = _ControlStub()
    celery_app = SimpleNamespace(control=control)

    monkeypatch.setattr(
        creator_runs_utils,
        "import_module",
        lambda _name: SimpleNamespace(task_tracking_service=tracking),
    )
    original_import = builtins.__import__

    def _import(name: str, *args, **kwargs):
        if name == "celery_app":
            return SimpleNamespace(celery_app=celery_app)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)
    result = await creator_runs_utils._revoke_celery_ids(["ok-1", "fail-1", "ok-2"], 1)
    assert result is False
