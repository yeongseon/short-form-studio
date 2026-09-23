"""Cleanup failure must not replace cancellation or prevent later cleanup."""

import logging
from pathlib import Path

import pytest
from creator_provider.exceptions import ProviderError

from .scene_cancellation_support import SceneCase, scene_case as scene_case
from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import runner_case as runner_case


def test_unlink_failure_warns_without_losing_cancelled_result(
    scene_case: SceneCase, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    # Given an earlier failed scene output plus a second generated output.
    case = scene_case
    case.provider.released.set()
    original_generate = case.provider.generate
    original_unlink = Path.unlink
    attempted: list[Path] = []

    async def generate(prompt: str, params: dict[str, str]):
        result = await original_generate(prompt, params)
        if prompt == "shot-0":
            raise ProviderError("unavailable")
        await case.cancel()
        return result

    def unlink(path: Path, missing_ok: bool = False) -> None:
        attempted.append(path)
        if len(attempted) == 1:
            raise PermissionError("secret-token=never-log-this")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(case.provider, "generate", generate)
    monkeypatch.setattr(Path, "unlink", unlink)
    caplog.set_level(logging.WARNING)
    # When cancellation triggers cleanup through the real task.
    result = case.invoke()
    # Then all outputs were attempted, cancellation survived, and warning is redacted.
    assert result["status"] == "cancelled"
    assert set(attempted) == set(case.provider.paths)
    assert not attempted[1].exists()
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert warnings
    assert "secret-token" not in caplog.text
    assert all(record.exc_info is None for record in warnings)
