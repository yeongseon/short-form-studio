"""Test that ProviderTimeoutError and RateLimitError are re-raised unchanged for all task modules.

Each task module must preserve these provider exceptions without mapping them to
a generic ProviderError, allowing Celery's retry mechanism to handle them.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from creator_provider.exceptions import ProviderTimeoutError, RateLimitError
from tasks import (
    generate_audio as generate_audio_module,
    generate_paragraph_audio as generate_paragraph_audio_module,
)


# ============================================================================
# Shared Test Infrastructure
# ============================================================================


@dataclass
class _FakeEntry:
    provider_type: str = "test"
    endpoint: str = "http://test:1234"
    requires_gpu: bool = False
    default_params: dict[str, object] | None = None


class _FakeProvider:
    """Generic fake provider for any task."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[Any] = []

    async def generate(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error

    async def transcribe(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error


class _FakeRegistry:
    def __init__(self, entry: _FakeEntry, provider: _FakeProvider) -> None:
        self.entry = entry
        self.provider = provider

    def resolve(self, _model_key: str) -> _FakeEntry:
        return self.entry

    def get_provider(self, _model_key: str) -> _FakeProvider:
        return self.provider


class _FakeStorage:
    """Minimal storage that allows tasks to proceed."""

    def __init__(self, run_id: int = 1, stage: str = "VISUAL_ASSET_REVIEW") -> None:
        self._run_id = run_id
        self._stage = stage

    async def get_run(self, run_id: int) -> dict[str, object] | None:
        if run_id == self._run_id:
            return {"id": run_id, "current_stage": self._stage}
        return None

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, object] | None]:
        return False, None

    async def update_run(self, run_id: int, updates: dict[str, object]) -> dict[str, object]:
        return {"id": run_id, **updates}


def _make_storage(run_id: int = 1, stage: str = "VISUAL_ASSET_REVIEW") -> _FakeStorage:
    return _FakeStorage(run_id, stage)


def _patch_registry(monkeypatch: pytest.MonkeyPatch, module: Any, registry: _FakeRegistry) -> None:
    """Patch the ProviderRegistry for a module."""

    class _ProviderRegistry:
        @staticmethod
        def create_default() -> _FakeRegistry:
            return registry

    monkeypatch.setattr(module, "ProviderRegistry", _ProviderRegistry)


# ============================================================================
# Tests for generate_audio
# ============================================================================


class _FakeAudioService:
    def __init__(self, artifact_id: int = 1) -> None:
        self.artifact_id = artifact_id
        self.calls: list[dict[str, object]] = []

    async def create_artifact(
        self,
        run_id: int,
        path: str,
        *,
        model_used: str | None = None,
        provider_type: str | None = None,
        voice: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "run_id": run_id,
                "path": path,
                "model_used": model_used,
                "provider_type": provider_type,
                "voice": voice,
            }
        )
        return SimpleNamespace(id=self.artifact_id, path=path)


class _FakeScriptService:
    def __init__(self, draft: Any = None) -> None:
        self.draft = draft

    async def get_active_draft(self, _run_id: int) -> Any:
        return self.draft


class _FakeScriptDraft:
    def __init__(self, markdown_content: str = "") -> None:
        self.markdown_content = markdown_content


def test_generate_audio_preserves_provider_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider(error=ProviderTimeoutError("timeout"))
    _patch_registry(monkeypatch, generate_audio_module, _FakeRegistry(_FakeEntry(), provider))

    script_service = _FakeScriptService(draft=_FakeScriptDraft(markdown_content="Test"))
    audio_service = _FakeAudioService(artifact_id=1)
    storage = _make_storage(run_id=1, stage="AUDIO_GENERATING")

    monkeypatch.setattr(generate_audio_module, "_script_service", script_service)
    monkeypatch.setattr(generate_audio_module, "_audio_service", audio_service)
    monkeypatch.setattr(generate_audio_module, "_run_service", SimpleNamespace(storage=storage))

    task = generate_audio_module.generate_audio
    run_callable = getattr(task, "run", task)

    with pytest.raises(ProviderTimeoutError, match="timeout"):
        run_callable(run_id=1)


def test_generate_audio_preserves_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider(error=RateLimitError("rate limited"))
    _patch_registry(monkeypatch, generate_audio_module, _FakeRegistry(_FakeEntry(), provider))

    script_service = _FakeScriptService(draft=_FakeScriptDraft(markdown_content="Test"))
    audio_service = _FakeAudioService(artifact_id=1)
    storage = _make_storage(run_id=1, stage="AUDIO_GENERATING")

    monkeypatch.setattr(generate_audio_module, "_script_service", script_service)
    monkeypatch.setattr(generate_audio_module, "_audio_service", audio_service)
    monkeypatch.setattr(generate_audio_module, "_run_service", SimpleNamespace(storage=storage))

    task = generate_audio_module.generate_audio
    run_callable = getattr(task, "run", task)

    with pytest.raises(RateLimitError, match="rate limited"):
        run_callable(run_id=1)


# ============================================================================
# Tests for generate_paragraph_audio
# ============================================================================


class _FakeAudioServiceForParagraph:
    def __init__(self, artifact_id: int = 1) -> None:
        self.artifact_id = artifact_id
        self.calls: list[dict[str, object]] = []

    async def create_paragraph_artifact(
        self,
        run_id: int,
        section_id: str,
        path: str,
        *,
        model_used: str | None = None,
        provider_type: str | None = None,
        voice: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "run_id": run_id,
                "section_id": section_id,
                "path": path,
                "model_used": model_used,
                "provider_type": provider_type,
                "voice": voice,
            }
        )
        return SimpleNamespace(id=self.artifact_id, path=path)


def test_generate_paragraph_audio_preserves_provider_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider(error=ProviderTimeoutError("timeout"))
    _patch_registry(
        monkeypatch, generate_paragraph_audio_module, _FakeRegistry(_FakeEntry(), provider)
    )

    audio_service = _FakeAudioServiceForParagraph(artifact_id=1)
    storage = _make_storage(run_id=1, stage="AUDIO_GENERATING")

    monkeypatch.setattr(generate_paragraph_audio_module, "_audio_service", audio_service)
    monkeypatch.setattr(
        generate_paragraph_audio_module, "_run_service", SimpleNamespace(storage=storage)
    )

    task = generate_paragraph_audio_module.generate_paragraph_audio
    run_callable = getattr(task, "run", task)

    with pytest.raises(ProviderTimeoutError, match="timeout"):
        run_callable(run_id=1, section_id="s1", section_text="Test")


def test_generate_paragraph_audio_preserves_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider(error=RateLimitError("rate limited"))
    _patch_registry(
        monkeypatch, generate_paragraph_audio_module, _FakeRegistry(_FakeEntry(), provider)
    )

    audio_service = _FakeAudioServiceForParagraph(artifact_id=1)
    storage = _make_storage(run_id=1, stage="AUDIO_GENERATING")

    monkeypatch.setattr(generate_paragraph_audio_module, "_audio_service", audio_service)
    monkeypatch.setattr(
        generate_paragraph_audio_module, "_run_service", SimpleNamespace(storage=storage)
    )

    task = generate_paragraph_audio_module.generate_paragraph_audio
    run_callable = getattr(task, "run", task)

    with pytest.raises(RateLimitError, match="rate limited"):
        run_callable(run_id=1, section_id="s1", section_text="Test")
