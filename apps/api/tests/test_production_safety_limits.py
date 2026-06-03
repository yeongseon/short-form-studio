import importlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest


def _load_api_module(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    sys.modules.pop("shorts_api.main", None)
    return importlib.import_module("shorts_api.main")


def _load_worker_module(monkeypatch: pytest.MonkeyPatch, module_name: str):
    worker_file = Path(__file__).resolve().parents[2] / "worker-orchestrator" / "celery_app.py"
    spec = importlib.util.spec_from_file_location(module_name, worker_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setenv("ENVIRONMENT", "development")
    sys.modules.pop(module_name, None)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_worker_applies_memory_setrlimit_from_env(monkeypatch: pytest.MonkeyPatch):
    setrlimit_mock = Mock()
    monkeypatch.setenv("MAX_MEMORY_MB", "2048")

    import resource

    monkeypatch.setattr(resource, "setrlimit", setrlimit_mock)
    module = _load_worker_module(monkeypatch, "worker_orchestrator_celery_app_test")

    # Resource limits are now applied inside _apply_resource_limits(), not at import
    module._apply_resource_limits()

    expected_bytes = 2048 * 1024 * 1024
    setrlimit_mock.assert_called_once_with(
        resource.RLIMIT_AS,
        (expected_bytes, expected_bytes),
    )


@pytest.mark.asyncio
async def test_cpu_monitor_triggers_shutdown_flag(monkeypatch: pytest.MonkeyPatch):
    from shorts_api import lifecycle
    lifecycle.shutdown_state.is_shutting_down = False
    kill_mock = Mock(side_effect=SystemExit(1))

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(lifecycle.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        lifecycle,
        "_cpu_usage_percent",
        lambda _cpu_seconds, _wall_seconds: (float(lifecycle.MAX_CPU_PERCENT) + 1.0, 0.0, 0.0),
    )
    monkeypatch.setattr(lifecycle.os, "kill", kill_mock)

    with pytest.raises(SystemExit, match="1"):
        await lifecycle._monitor_cpu_limit()

    assert lifecycle.shutdown_state.is_shutting_down is True
    # Reset to avoid polluting other tests
    lifecycle.shutdown_state.is_shutting_down = False


@pytest.mark.asyncio
async def test_api_startup_fails_when_setrlimit_fails(monkeypatch: pytest.MonkeyPatch):
    from shorts_api import lifecycle

    def fail_setrlimit(_limit, _values):
        raise OSError("setrlimit failed")

    monkeypatch.setattr(lifecycle, "ENABLE_PROCESS_RESOURCE_GUARD", True)
    monkeypatch.setattr(lifecycle.resource, "setrlimit", fail_setrlimit)

    with pytest.raises(OSError, match="setrlimit failed"):
        from shorts_api.main import app
        async with lifecycle.lifespan(app):
            pass
