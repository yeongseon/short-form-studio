import asyncio
from datetime import datetime, timezone
from importlib import import_module

AdminService = import_module("creator_service.admin_service").AdminService


class _FakeAcquire:
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
        return _FakeAcquire(self._connection)


class _FakeRedis:
    def __init__(self, lengths=None):
        self._lengths = lengths or {}

    async def ping(self):
        return True

    async def llen(self, key):
        return self._lengths.get(key, 0)

    async def aclose(self):
        return None


def test_get_storage_stats_counts_files_and_size(monkeypatch, tmp_path) -> None:
    (tmp_path / "a.txt").write_text("abc", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.bin").write_bytes(b"12345")

    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    service = AdminService()

    result = asyncio.run(service.get_storage_stats())

    assert result["file_count"] == 2
    assert result["total_size_bytes"] == 8


def test_get_queue_depth_with_mocked_redis(monkeypatch) -> None:
    service = AdminService()

    monkeypatch.setattr(
        service,
        "_redis_client",
        lambda: _FakeRedis(lengths={"celery": 4, "gpu_queue": 2}),
    )

    result = asyncio.run(service.get_queue_depth())

    assert result == {"celery": 4, "gpu_queue": 2}


def test_get_stuck_runs_queries_pool(monkeypatch) -> None:
    class _Conn:
        async def fetch(self, query, stages, cutoff):
            assert "current_stage = ANY" in query
            assert isinstance(stages, list)
            assert cutoff.tzinfo is timezone.utc
            return [
                {
                    "id": 10,
                    "project_id": 5,
                    "current_stage": "SCRIPT_GENERATING",
                    "status": "running",
                    "active_task_id": "task-1",
                    "updated_at": datetime.now(tz=timezone.utc),
                }
            ]

    async def _fake_get_pool():
        return _FakePool(_Conn())

    monkeypatch.setattr("creator_service.admin_service.get_pool", _fake_get_pool)
    service = AdminService()

    result = asyncio.run(service.get_stuck_runs(threshold_minutes=30))

    assert len(result) == 1
    assert result[0]["id"] == 10


def test_unstick_run_updates_generating_stage(monkeypatch) -> None:
    class _Conn:
        async def fetchrow(self, query, *args):
            if query.startswith("SELECT"):
                return {"id": 42, "current_stage": "SCRIPT_GENERATING"}
            return {
                "id": 42,
                "current_stage": "SCRIPT_REVIEW",
                "updated_at": datetime.now(tz=timezone.utc),
            }

    async def _fake_get_pool():
        return _FakePool(_Conn())

    monkeypatch.setattr("creator_service.admin_service.get_pool", _fake_get_pool)
    service = AdminService()

    result = asyncio.run(service.unstick_run("42"))

    assert result["ok"] is True
    assert result["previous_stage"] == "SCRIPT_GENERATING"
    assert result["current_stage"] == "SCRIPT_REVIEW"


def test_unstick_run_rejects_non_generating_stage(monkeypatch) -> None:
    class _Conn:
        async def fetchrow(self, query, *args):
            return {"id": 42, "current_stage": "SCRIPT_REVIEW"}

    async def _fake_get_pool():
        return _FakePool(_Conn())

    monkeypatch.setattr("creator_service.admin_service.get_pool", _fake_get_pool)
    service = AdminService()

    result = asyncio.run(service.unstick_run("42"))

    assert result["ok"] is False
    assert result["error"] == "Run is not in a generating stage"


def test_get_system_health_with_mocked_connections(monkeypatch) -> None:
    class _Conn:
        async def fetchval(self, query):
            assert query == "SELECT 1"
            return 1

    async def _fake_get_pool():
        return _FakePool(_Conn())

    monkeypatch.setattr("creator_service.admin_service.get_pool", _fake_get_pool)
    service = AdminService()
    monkeypatch.setattr(service, "_redis_client", lambda: _FakeRedis())

    result = asyncio.run(service.get_system_health())

    assert result["status"] == "ok"
    assert result["db"]["ok"] is True
    assert result["redis"]["ok"] is True
    assert result["uptime_seconds"] >= 0
