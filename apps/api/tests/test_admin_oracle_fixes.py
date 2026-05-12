import asyncio
import logging
from datetime import datetime, timedelta, timezone
from importlib import import_module


admin_routes = import_module("shorts_api.routes.admin")
admin_service_module = import_module("creator_service.admin_service")


class _FakeTaskBroker:
    def __init__(self, failing_task_ids: set[str] | None = None) -> None:
        self.failing_task_ids = failing_task_ids or set()

    async def revoke_task(self, task_id: str) -> None:
        if task_id in self.failing_task_ids:
            raise RuntimeError(f"broker-failure-{task_id}")


class _FakeConnection:
    def __init__(self) -> None:
        self._old_updated_at = datetime.now(tz=timezone.utc) - timedelta(hours=2)

    async def fetchrow(self, query: str, *_args):
        if query.strip().startswith("SELECT id, current_stage"):
            return {
                "id": 42,
                "current_stage": "SCRIPT_GENERATING",
                "status": "running",
                "active_task_id": '["task-ok","task-fail"]',
                "updated_at": self._old_updated_at,
            }
        if query.strip().startswith("UPDATE creator_runs"):
            return {
                "id": 42,
                "current_stage": "SCRIPT_REVIEW",
                "status": "pending",
                "updated_at": self._old_updated_at,
            }
        return None

    async def fetch(self, query: str, *_args):
        if "creator_artifacts" in query:
            return [{"artifact_type": "script"}]
        return []


class _FakePoolAcquire:
    def __init__(self, connection):
        self._connection = connection

    async def __aenter__(self):
        return self._connection

    async def __aexit__(self, exc_type, exc, tb):
        return None


class _FakePool:
    def __init__(self, connection):
        self._connection = connection

    def acquire(self):
        return _FakePoolAcquire(self._connection)


def test_unstick_run_returns_ok_with_warnings_when_revoke_fails(monkeypatch) -> None:
    async def _get_pool():
        return _FakePool(_FakeConnection())

    monkeypatch.setattr(admin_service_module, "get_pool", _get_pool)
    tracking_module = import_module("creator_service.task_tracking_service")

    async def _get_active_celery_ids(_run_id: int) -> list[str]:
        return ["task-ok", "task-fail"]

    async def _mark_revoked(_task_id: str):
        return None

    monkeypatch.setattr(
        tracking_module.task_tracking_service,
        "get_active_celery_ids",
        _get_active_celery_ids,
    )
    monkeypatch.setattr(tracking_module.task_tracking_service, "mark_revoked", _mark_revoked)
    service = admin_service_module.AdminService(task_broker=_FakeTaskBroker({"task-fail"}))

    result = asyncio.run(service.unstick_run("42"))

    assert result["ok"] is True
    assert result["run_id"] == "42"
    assert result["warnings"] == ["Failed to revoke task task-fail: broker-failure-task-fail"]


def test_admin_clear_cache_logs_sanitized_pattern_without_newlines(caplog) -> None:
    async def _fake_clear_cache(*, key_pattern: str | None = None, dry_run: bool = False):
        return {
            "ok": True,
            "deleted_keys": 0,
            "key_pattern": key_pattern or "cache:*",
            "dry_run": dry_run,
            "matched_keys": [],
        }

    malicious_pattern = "cache:test:*\nFORGED_LOG\rLINE"
    caplog.set_level(logging.WARNING)

    original = admin_routes.admin_service.clear_cache
    admin_routes.admin_service.clear_cache = _fake_clear_cache
    try:
        result = asyncio.run(
            admin_routes.admin_clear_cache(key_pattern=malicious_pattern, dry_run=True)
        )
    finally:
        admin_routes.admin_service.clear_cache = original

    assert result["ok"] is True
    assert malicious_pattern not in caplog.text
    assert "cache:test:*FORGED_LOGLINE" in caplog.text


def test_unstick_run_returns_generic_internal_error(monkeypatch) -> None:
    async def _boom_pool():
        raise RuntimeError("DB_URL=postgres://secret@host/db")

    monkeypatch.setattr(admin_service_module, "get_pool", _boom_pool)
    service = admin_service_module.AdminService(task_broker=_FakeTaskBroker())

    result = asyncio.run(service.unstick_run("42"))

    assert result["ok"] is False
    assert result["error"] == "Internal error during unstick operation"
    assert "secret" not in result["error"]


def test_clear_cache_returns_generic_internal_error(monkeypatch) -> None:
    class _FailingScanIter:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise RuntimeError("redis://user:secret@localhost:6379/0")

    class _FailingRedisClient:
        def scan_iter(self, match=None):
            _ = match
            return _FailingScanIter()

        async def aclose(self) -> None:
            return None

    service = admin_service_module.AdminService(task_broker=_FakeTaskBroker())
    monkeypatch.setattr(service, "_redis_client", lambda: _FailingRedisClient())

    result = asyncio.run(service.clear_cache(key_pattern="cache:*", dry_run=False))

    assert result["ok"] is False
    assert result["error"] == "Internal error during cache operation"
    assert "secret" not in result["error"]
