"""Test resource guard opt-in functionality via env var."""

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
