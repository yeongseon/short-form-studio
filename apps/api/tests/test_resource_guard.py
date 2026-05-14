"""Test resource guard opt-in functionality via env var."""

import signal
from unittest.mock import Mock

import pytest


@pytest.fixture
def mock_apply_resource_limits():
    """Mock _apply_resource_limits function."""
    from unittest.mock import patch

    with patch("shorts_api.lifecycle._apply_resource_limits") as mock:
        yield mock


@pytest.mark.asyncio
async def test_resource_guard_disabled_by_default(monkeypatch, mock_apply_resource_limits):
    """Test that resource guard is disabled when env var is not set."""
    monkeypatch.delenv("ENABLE_PROCESS_RESOURCE_GUARD", raising=False)

    import importlib
    import shorts_api.lifecycle as lifecycle_module

    importlib.reload(lifecycle_module)

    assert not lifecycle_module.ENABLE_PROCESS_RESOURCE_GUARD

    from fastapi import FastAPI

    app = FastAPI(lifespan=lifecycle_module.lifespan)

    async with lifecycle_module.lifespan(app):
        pass

    mock_apply_resource_limits.assert_not_called()


@pytest.mark.asyncio
async def test_resource_guard_disabled_explicitly_false(monkeypatch, mock_apply_resource_limits):
    """Test that resource guard is disabled when env var is 'false'."""
    monkeypatch.setenv("ENABLE_PROCESS_RESOURCE_GUARD", "false")

    import importlib
    import shorts_api.lifecycle as lifecycle_module

    importlib.reload(lifecycle_module)

    assert not lifecycle_module.ENABLE_PROCESS_RESOURCE_GUARD

    from fastapi import FastAPI

    app = FastAPI(lifespan=lifecycle_module.lifespan)

    async with lifecycle_module.lifespan(app):
        pass

    mock_apply_resource_limits.assert_not_called()


@pytest.mark.asyncio
async def test_resource_guard_disabled_zero(monkeypatch, mock_apply_resource_limits):
    """Test that resource guard is disabled when env var is '0'."""
    monkeypatch.setenv("ENABLE_PROCESS_RESOURCE_GUARD", "0")

    import importlib
    import shorts_api.lifecycle as lifecycle_module

    importlib.reload(lifecycle_module)

    assert not lifecycle_module.ENABLE_PROCESS_RESOURCE_GUARD

    from fastapi import FastAPI

    app = FastAPI(lifespan=lifecycle_module.lifespan)

    async with lifecycle_module.lifespan(app):
        pass

    mock_apply_resource_limits.assert_not_called()


@pytest.mark.asyncio
async def test_resource_guard_enabled_yes(monkeypatch):
    """Test that resource guard is enabled when env var is 'yes'."""
    monkeypatch.setenv("ENABLE_PROCESS_RESOURCE_GUARD", "yes")

    import importlib
    import shorts_api.lifecycle as lifecycle_module

    importlib.reload(lifecycle_module)

    assert lifecycle_module.ENABLE_PROCESS_RESOURCE_GUARD


@pytest.mark.asyncio
async def test_resource_guard_enabled_on(monkeypatch):
    """Test that resource guard is enabled when env var is 'on'."""
    monkeypatch.setenv("ENABLE_PROCESS_RESOURCE_GUARD", "on")

    import importlib
    import shorts_api.lifecycle as lifecycle_module

    importlib.reload(lifecycle_module)

    assert lifecycle_module.ENABLE_PROCESS_RESOURCE_GUARD


@pytest.mark.asyncio
async def test_resource_guard_enabled_1(monkeypatch):
    """Test that resource guard is enabled when env var is '1'."""
    monkeypatch.setenv("ENABLE_PROCESS_RESOURCE_GUARD", "1")

    import importlib
    import shorts_api.lifecycle as lifecycle_module

    importlib.reload(lifecycle_module)

    assert lifecycle_module.ENABLE_PROCESS_RESOURCE_GUARD


@pytest.mark.asyncio
async def test_resource_guard_enabled_true(monkeypatch):
    """Test that resource guard is enabled when env var is 'true'."""
    monkeypatch.setenv("ENABLE_PROCESS_RESOURCE_GUARD", "true")

    import importlib
    import shorts_api.lifecycle as lifecycle_module

    importlib.reload(lifecycle_module)

    assert lifecycle_module.ENABLE_PROCESS_RESOURCE_GUARD


@pytest.mark.asyncio
async def test_cpu_monitor_task_not_created_when_disabled(monkeypatch):
    """Test that CPU monitor task is NOT created when resource guard is disabled."""
    from unittest.mock import patch

    monkeypatch.delenv("ENABLE_PROCESS_RESOURCE_GUARD", raising=False)

    import importlib
    import shorts_api.lifecycle as lifecycle_module

    importlib.reload(lifecycle_module)

    with patch("asyncio.create_task") as mock_create_task:
        from fastapi import FastAPI

        app = FastAPI(lifespan=lifecycle_module.lifespan)

        async with lifecycle_module.lifespan(app):
            pass

        # Verify create_task was NOT called
        mock_create_task.assert_not_called()


def test_sigterm_handler_marks_shutdown_flag() -> None:
    import shorts_api.lifecycle as lifecycle_module

    lifecycle_module.shutdown_state.is_shutting_down = False
    lifecycle_module._handle_sigterm(15, None)

    assert lifecycle_module.shutdown_state.is_shutting_down is True


@pytest.mark.asyncio
async def test_lifespan_sigterm_handler_chains_to_previous_handler(monkeypatch) -> None:
    import importlib
    import shorts_api.lifecycle as lifecycle_module
    from fastapi import FastAPI

    importlib.reload(lifecycle_module)
    lifecycle_module.shutdown_state.is_shutting_down = False

    previous_handler = Mock()
    monkeypatch.setattr(lifecycle_module.signal, "getsignal", lambda sig: previous_handler)
    monkeypatch.setattr(lifecycle_module.signal, "signal", lambda *_args: previous_handler)

    app = FastAPI(lifespan=lifecycle_module.lifespan)
    async with lifecycle_module.lifespan(app):
        lifecycle_module._handle_sigterm(signal.SIGTERM, None)

    previous_handler.assert_called_once_with(signal.SIGTERM, None)


@pytest.mark.asyncio
async def test_lifespan_restores_previous_sigterm_handler_after_exit(monkeypatch) -> None:
    import importlib
    import shorts_api.lifecycle as lifecycle_module
    from fastapi import FastAPI

    importlib.reload(lifecycle_module)

    previous_handler = Mock()
    signal_calls: list[tuple[int, object]] = []

    def _getsignal(_sig: int) -> object:
        return previous_handler

    def _signal(sig: int, handler: object) -> object:
        signal_calls.append((sig, handler))
        return previous_handler

    monkeypatch.setattr(lifecycle_module.signal, "getsignal", _getsignal)
    monkeypatch.setattr(lifecycle_module.signal, "signal", _signal)

    app = FastAPI(lifespan=lifecycle_module.lifespan)
    async with lifecycle_module.lifespan(app):
        pass

    # Should register SIGTERM and SIGINT handlers on startup
    sigterm_setup_call = (signal.SIGTERM, lifecycle_module._handle_sigterm)
    sigint_setup_call = (signal.SIGINT, lifecycle_module._handle_sigint)
    
    # Find setup calls (before restoration)
    assert sigterm_setup_call in signal_calls
    assert sigint_setup_call in signal_calls
    
    # Last two calls should be restoration of SIGTERM and SIGINT (in that order)
    # SIGTERM is restored first, then SIGINT
    assert signal_calls[-2] == (signal.SIGTERM, previous_handler)
    assert signal_calls[-1] == (signal.SIGINT, previous_handler)
