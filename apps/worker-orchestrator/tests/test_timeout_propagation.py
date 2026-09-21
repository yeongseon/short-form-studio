# pyright: reportMissingImports=false
"""Verify SoftTimeLimitExceeded propagates through inner except blocks.

Oracle Round 3 identified that broad ``except Exception`` blocks around
provider calls could swallow Celery's ``SoftTimeLimitExceeded``, preventing
the outer timeout handler from marking the run as FAILED.

These tests assert that a SoftTimeLimitExceeded raised inside a provider
call escapes the inner exception handler and reaches the outer timeout
handler (which marks the run FAILED via conditional_update_run).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from celery.exceptions import SoftTimeLimitExceeded


def test_generate_script_propagates_soft_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """SoftTimeLimitExceeded raised during provider.generate must not be
    swallowed by the inner except-Exception block."""
    from tasks import generate_script as mod

    fake_run = {
        "id": 1,
        "project_id": 1,
        "current_stage": "SCRIPT_GENERATING",
        "status": "running",
        "idea_brief": "test idea",
        "active_task_id": "test-celery-id",
    }

    # Mock storage
    mock_storage = AsyncMock()
    mock_storage.get_run = AsyncMock(return_value=fake_run)
    mock_storage.conditional_update_run = AsyncMock(return_value=(True, fake_run))

    mock_run_service = MagicMock()
    mock_run_service.storage = mock_storage

    monkeypatch.setattr("tasks.task_runner._run_service", mock_run_service)

    # Mock GPU lock
    monkeypatch.setattr("tasks.task_runner.acquire_gpu_lock", Mock(return_value="lock-1"))
    monkeypatch.setattr("tasks.task_runner.release_gpu_lock", Mock())

    # Mock ProviderRegistry to return a provider that raises SoftTimeLimitExceeded
    mock_provider = AsyncMock()
    mock_provider.generate = AsyncMock(side_effect=SoftTimeLimitExceeded())

    mock_registry = MagicMock()
    mock_entry = MagicMock()
    mock_entry.default_params = {}
    mock_registry.resolve.return_value = mock_entry
    mock_registry.get_provider.return_value = mock_provider

    monkeypatch.setattr(mod, "get_default_registry", lambda: mock_registry)

    # Mock script service
    mock_script_service = MagicMock()
    monkeypatch.setattr(mod, "_script_service", mock_script_service)

    with pytest.raises(SoftTimeLimitExceeded):
        # Celery bound tasks: call without self, Celery injects it
        mod.generate_script.run(
            run_id=1,
            idea_brief="test idea",
            model_key="test-model",
            instructions=None,
        )

    # The outer timeout handler should have attempted to mark run as FAILED
    mock_storage.conditional_update_run.assert_called()
