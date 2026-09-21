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
    def __init__(self, lengths=None, keys=None):
        self._lengths = lengths or {}
        self._keys = list(keys or [])
        self.deleted: list[str] = []

    async def ping(self):
        return True

    async def llen(self, key):
        return self._lengths.get(key, 0)

    async def scan_iter(self, match="*"):
        if match.endswith("*"):
            prefix = match[:-1]
            for key in self._keys:
                if key.startswith(prefix):
                    yield key
            return
        for key in self._keys:
            if key == match:
                yield key

    async def delete(self, key):
        self.deleted.append(key)
        return 1

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
        lambda: _FakeRedis(lengths={"creator": 4}),
    )

    result = asyncio.run(service.get_queue_depth())

    assert result == {"creator": 4}


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
        async def fetch(self, query, *_args):
            assert "SELECT DISTINCT artifact_type FROM creator_artifacts" in query
            return [{"artifact_type": "script"}]

        async def fetchrow(self, query, *_args):
            if query.startswith("SELECT"):
                return {
                    "id": 42,
                    "current_stage": "SCRIPT_GENERATING",
                    "status": "running",
                    "active_task_id": None,
                    "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                }
            return {
                "id": 42,
                "current_stage": "SCRIPT_REVIEW",
                "status": "pending",
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
        async def fetchrow(self, _query, *_args):
            return {
                "id": 42,
                "current_stage": "SCRIPT_REVIEW",
                "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            }

    async def _fake_get_pool():
        return _FakePool(_Conn())

    monkeypatch.setattr("creator_service.admin_service.get_pool", _fake_get_pool)
    service = AdminService()

    result = asyncio.run(service.unstick_run("42"))

    assert result["ok"] is False
    assert result["error"] == "Run is not in a generating stage"


def test_unstick_run_rejects_if_not_stuck_long_enough(monkeypatch) -> None:
    class _Conn:
        async def fetchrow(self, _query, *_args):
            return {
                "id": 42,
                "current_stage": "SCRIPT_GENERATING",
                "status": "running",
                "updated_at": datetime.now(tz=timezone.utc),
            }

    async def _fake_get_pool():
        return _FakePool(_Conn())

    monkeypatch.setattr("creator_service.admin_service.get_pool", _fake_get_pool)
    service = AdminService()

    result = asyncio.run(service.unstick_run("42"))

    assert result["ok"] is False
    assert result["error"] == "Run has not been stuck long enough"


def test_unstick_run_requires_artifacts_before_advancing(monkeypatch) -> None:
    class _Conn:
        def __init__(self, artifact_types=None):
            self._artifact_types = artifact_types or []

        async def fetchrow(self, query, *_args):
            if query.startswith("SELECT"):
                return {
                    "id": 42,
                    "current_stage": "SCRIPT_GENERATING",
                    "status": "running",
                    "active_task_id": None,
                    "updated_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
                }
            return {
                "id": 42,
                "current_stage": "SCRIPT_REVIEW",
                "status": "pending",
                "updated_at": datetime.now(tz=timezone.utc),
            }

        async def fetch(self, query, *_args):
            assert "SELECT DISTINCT artifact_type FROM creator_artifacts" in query
            return [{"artifact_type": artifact_type} for artifact_type in self._artifact_types]

    async def _fake_get_pool_missing():
        return _FakePool(_Conn(artifact_types=[]))

    async def _fake_get_pool_with_script():
        return _FakePool(_Conn(artifact_types=["script"]))

    monkeypatch.setattr("creator_service.admin_service.get_pool", _fake_get_pool_missing)
    service = AdminService()

    missing_result = asyncio.run(service.unstick_run("42"))

    assert missing_result["ok"] is False
    assert missing_result["error"] == (
        "Cannot advance to SCRIPT_REVIEW: missing required artifacts: ['script']"
    )

    monkeypatch.setattr("creator_service.admin_service.get_pool", _fake_get_pool_with_script)

    success_result = asyncio.run(service.unstick_run("42"))

    assert success_result["ok"] is True
    assert success_result["current_stage"] == "SCRIPT_REVIEW"


def test_clear_cache_only_deletes_matching_prefix(monkeypatch) -> None:
    service = AdminService()
    fake_redis = _FakeRedis(keys=["cache:test:a", "cache:test:b", "session:1", "gpu_queue"])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    result = asyncio.run(service.clear_cache(key_pattern="cache:test:*", dry_run=False))

    assert result["ok"] is True
    assert result["deleted_keys"] == 2
    assert sorted(result["matched_keys"]) == ["cache:test:a", "cache:test:b"]
    assert sorted(fake_redis.deleted) == ["cache:test:a", "cache:test:b"]


def test_clear_cache_dry_run_reports_without_deleting(monkeypatch) -> None:
    service = AdminService()
    fake_redis = _FakeRedis(keys=["cache:test:a", "cache:test:b", "session:1"])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    result = asyncio.run(service.clear_cache(key_pattern="cache:test:*", dry_run=True))

    assert result["ok"] is True
    assert result["deleted_keys"] == 0
    assert result["dry_run"] is True
    assert sorted(result["matched_keys"]) == ["cache:test:a", "cache:test:b"]
    assert fake_redis.deleted == []


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


# --- PR 1: Allowlist + unsafe pattern rejection tests ---


def test_clear_cache_rejects_bare_cache_wildcard(monkeypatch) -> None:
    """cache:* is too broad — must specify a sub-namespace."""
    service = AdminService()
    fake_redis = _FakeRedis(keys=["cache:a", "cache:b"])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    result = asyncio.run(service.clear_cache(key_pattern="cache:*", dry_run=False))

    assert result["ok"] is False
    assert "too broad" in result["error"].lower() or "specific" in result["error"].lower()
    assert fake_redis.deleted == []


def test_clear_cache_allows_specific_sub_namespace(monkeypatch) -> None:
    """cache:model:* should be allowed as it targets a specific sub-namespace."""
    service = AdminService()
    fake_redis = _FakeRedis(keys=["cache:model:gpt4", "cache:model:claude", "cache:other:x"])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    result = asyncio.run(service.clear_cache(key_pattern="cache:model:*", dry_run=False))

    assert result["ok"] is True
    assert result["deleted_keys"] == 2
    assert sorted(result["matched_keys"]) == ["cache:model:claude", "cache:model:gpt4"]


def test_clear_cache_rejects_unsafe_glob_characters(monkeypatch) -> None:
    """Patterns with [, ?, or \\ should be rejected as unsafe."""
    service = AdminService()
    fake_redis = _FakeRedis(keys=[])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    for unsafe_pattern in ["cache:model:[a-z]*", "cache:model:?", "cache:model:\\*"]:
        result = asyncio.run(service.clear_cache(key_pattern=unsafe_pattern, dry_run=False))
        assert result["ok"] is False, f"Pattern {unsafe_pattern} should be rejected"
        assert "unsafe" in result["error"].lower() or "character" in result["error"].lower()


def test_clear_cache_rejects_pattern_without_sub_namespace(monkeypatch) -> None:
    """cache:something without a colon separator after sub-namespace should be rejected."""
    service = AdminService()
    fake_redis = _FakeRedis(keys=[])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    # "cache:x" with no trailing colon or wildcard after sub-namespace
    result = asyncio.run(service.clear_cache(key_pattern="cache:", dry_run=False))
    assert result["ok"] is False


def test_clear_cache_allows_exact_key_in_sub_namespace(monkeypatch) -> None:
    """cache:model:gpt4 (exact key, no wildcard) should be allowed."""
    service = AdminService()
    fake_redis = _FakeRedis(keys=["cache:model:gpt4"])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    result = asyncio.run(service.clear_cache(key_pattern="cache:model:gpt4", dry_run=False))

    assert result["ok"] is True
    assert result["deleted_keys"] == 1


def test_clear_cache_default_pattern_uses_env_with_sub_namespace(monkeypatch) -> None:
    """Default pattern from env should also pass validation."""
    monkeypatch.setenv("ADMIN_CACHE_CLEAR_PREFIX", "cache:session:*")
    service = AdminService()
    fake_redis = _FakeRedis(keys=["cache:session:abc"])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    result = asyncio.run(service.clear_cache(key_pattern=None, dry_run=False))

    assert result["ok"] is True


def test_clear_cache_default_env_bare_wildcard_rejected(monkeypatch) -> None:
    """Even the env default should be rejected if it's cache:*."""
    monkeypatch.setenv("ADMIN_CACHE_CLEAR_PREFIX", "cache:*")
    service = AdminService()
    fake_redis = _FakeRedis(keys=["cache:a"])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    result = asyncio.run(service.clear_cache(key_pattern=None, dry_run=False))

    assert result["ok"] is False


def test_clear_cache_rejects_wildcard_in_namespace_segment(monkeypatch) -> None:
    """cache:*:* and cache:model*:* should be rejected — wildcard in namespace."""
    service = AdminService()
    fake_redis = _FakeRedis(keys=[])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    for bypass_pattern in ["cache:*:*", "cache:model*:*", "cache:*:gpt4"]:
        result = asyncio.run(service.clear_cache(key_pattern=bypass_pattern, dry_run=False))
        assert result["ok"] is False, f"Pattern {bypass_pattern} should be rejected"
        assert fake_redis.deleted == []


def test_clear_cache_rejects_newline_in_pattern(monkeypatch) -> None:
    """Newlines in patterns should be rejected at service level (defense-in-depth)."""
    service = AdminService()
    fake_redis = _FakeRedis(keys=[])
    monkeypatch.setattr(service, "_redis_client", lambda: fake_redis)

    result = asyncio.run(service.clear_cache(key_pattern="cache:test:*\nFORGED", dry_run=False))
    assert result["ok"] is False
    assert "newline" in result["error"].lower()
