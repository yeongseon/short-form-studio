from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from tasks import generate_paragraph_audio as module


@dataclass
class FakeEntry:
    provider_type: str = "qwen_tts"
    endpoint: str = "http://tts-qwen3:8100"
    requires_gpu: bool = False
    default_params: dict[str, object] | None = None


class FakeProvider:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    async def generate(
        self,
        text: str,
        voice: str = "default",
        params: dict[str, object] | None = None,
    ) -> None:
        self.calls.append((text, voice, params))
        if self.error is not None:
            raise self.error


@dataclass
class FakeAudioArtifact:
    id: int
    path: str


class FakeAudioService:
    def __init__(self, artifact_id: int = 1) -> None:
        self.artifact_id = artifact_id
        self.calls: list[dict[str, object]] = []

    async def create_paragraph_artifact(
        self,
        run_id: int,
        section_id: int,
        path: str,
        *,
        model_used: str | None = None,
        provider_type: str | None = None,
        voice: str | None = None,
        storage_provider: str | None = None,
        storage_key: str | None = None,
    ) -> FakeAudioArtifact:
        call_data = {
            "run_id": run_id,
            "section_id": section_id,
            "path": path,
            "model_used": model_used,
            "provider_type": provider_type,
            "voice": voice,
            "storage_provider": storage_provider,
            "storage_key": storage_key,
        }
        self.calls.append(call_data)
        return FakeAudioArtifact(id=self.artifact_id, path=path)


class FakeRunStorage:
    def __init__(self, run_row: dict[str, Any] | None) -> None:
        self.run_row = run_row

    async def get_run(self, run_id: int) -> dict[str, Any] | None:
        if self.run_row is None:
            return None
        row = dict(self.run_row)
        row["id"] = run_id
        return row


class FakeRunService:
    def __init__(self, run_row: dict[str, Any] | None) -> None:
        self.storage = FakeRunStorage(run_row)


@dataclass
class FakeSection:
    section_id: str
    text: str
    display_text: str | None = None


@dataclass
class FakeDraft:
    markdown_content: str | None = None
    structured_script: list[FakeSection] | None = None


class FakeScriptService:
    def __init__(self, draft: FakeDraft | None) -> None:
        self.draft = draft
        self.calls: list[int] = []

    async def get_active_draft(self, run_id: int) -> FakeDraft | None:
        self.calls.append(run_id)
        return self.draft


class FakeRegistry:
    def __init__(self, entry: FakeEntry, provider: FakeProvider) -> None:
        self.entry = entry
        self.provider = provider

    def resolve(self, _model_key: str) -> FakeEntry:
        return self.entry

    def get_provider(self, _model_key: str) -> FakeProvider:
        return self.provider


def _patch_registry(monkeypatch: pytest.MonkeyPatch, registry: FakeRegistry) -> None:
    class _ProviderRegistry:
        @staticmethod
        def create_default() -> FakeRegistry:
            return registry

    monkeypatch.setattr(module, "ProviderRegistry", _ProviderRegistry)


def _patch_redis(monkeypatch: pytest.MonkeyPatch, redis_client: object) -> None:
    redis_stub = SimpleNamespace(Redis=SimpleNamespace(from_url=lambda _: redis_client))
    monkeypatch.setattr(module, "redis", redis_stub)


def _invoke_task(**kwargs: Any) -> dict[str, object]:
    task = module.generate_paragraph_audio
    run_callable = getattr(task, "run", task)
    return run_callable(**kwargs)


def test_generate_paragraph_audio_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False, default_params={"temperature": 0.2})
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    audio_service = FakeAudioService(artifact_id=33)
    monkeypatch.setattr(
        module,
        "_run_service",
        FakeRunService(
            {
                "current_stage": "AUDIO_GENERATING",
            }
        ),
    )
    script_service = FakeScriptService(
        FakeDraft(structured_script=[FakeSection(section_id="hook-1", text="Hello paragraph")])
    )
    monkeypatch.setattr(module, "_script_service", script_service)
    monkeypatch.setattr(module, "_audio_service", audio_service)

    result = _invoke_task(
        run_id=101,
        section_id="hook-1",
        tts_model="qwen3-tts",
        voice="en_US-lessac-medium",
    )

    assert result["status"] == "success"
    assert result["audio_artifact_id"] == 33
    assert result["run_id"] == 101
    assert result["section_id"] == "hook-1"
    assert result["tts_model"] == "qwen3-tts"
    assert result["voice"] == "en_US-lessac-medium"
    assert result["provider_type"] == "qwen_tts"
    assert result["endpoint"] == "http://tts-qwen3:8100"
    assert result["audio_path"] == "data/artifacts/101/audio/hook-1.wav"
    assert result["gpu_lock_acquired_at"] is None
    assert result["gpu_lock_released_at"] is None

    assert provider.calls == [
        (
            "Hello paragraph",
            "en_US-lessac-medium",
            {
                "temperature": 0.2,
                "output_path": "data/artifacts/101/audio/hook-1.wav",
            },
        )
    ]
    assert len(audio_service.calls) == 1
    call = audio_service.calls[0]
    assert call["run_id"] == 101
    assert call["section_id"] == "hook-1"
    assert call["path"] == "data/artifacts/101/audio/hook-1.wav"
    assert call["model_used"] == "qwen3-tts"
    assert call["provider_type"] == "qwen_tts"
    assert call["voice"] == "en_US-lessac-medium"
    assert call["storage_provider"] == "local"
    assert "storage_key" in call
    assert script_service.calls == [101]


def test_generate_paragraph_audio_with_gpu_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=True)
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    lock_calls: list[str] = []
    release_calls: list[str] = []
    monkeypatch.setattr(
        module,
        "acquire_gpu_lock",
        lambda _, task_id: (lock_calls.append(task_id) or f"{task_id}:fake-token"),
    )
    monkeypatch.setattr(
        module,
        "release_gpu_lock",
        lambda _, token: release_calls.append(token.split(":")[0]) or True,
    )

    audio_service = FakeAudioService(artifact_id=61)
    monkeypatch.setattr(
        module,
        "_run_service",
        FakeRunService(
            {
                "current_stage": "AUDIO_GENERATING",
            }
        ),
    )
    monkeypatch.setattr(
        module,
        "_script_service",
        FakeScriptService(
            FakeDraft(structured_script=[FakeSection(section_id="hook-2", text="Lock paragraph")])
        ),
    )
    monkeypatch.setattr(module, "_audio_service", audio_service)

    result = _invoke_task(run_id=105, section_id="hook-2")

    assert result["status"] == "success"
    assert result["gpu_lock_acquired_at"] is not None
    assert result["gpu_lock_released_at"] is not None
    assert lock_calls == ["para-105-hook-2"]
    assert release_calls == ["para-105-hook-2"]


def test_generate_paragraph_audio_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(error=RuntimeError("audio provider failed"))
    entry = FakeEntry(requires_gpu=True)
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    lock_calls: list[str] = []
    release_calls: list[str] = []
    monkeypatch.setattr(
        module,
        "acquire_gpu_lock",
        lambda _, task_id: (lock_calls.append(task_id) or f"{task_id}:fake-token"),
    )
    monkeypatch.setattr(
        module,
        "release_gpu_lock",
        lambda _, token: release_calls.append(token.split(":")[0]) or True,
    )

    audio_service = FakeAudioService()
    monkeypatch.setattr(
        module,
        "_run_service",
        FakeRunService(
            {
                "current_stage": "AUDIO_GENERATING",
            }
        ),
    )
    monkeypatch.setattr(
        module,
        "_script_service",
        FakeScriptService(
            FakeDraft(
                structured_script=[FakeSection(section_id="hook-3", text="Failure paragraph")]
            )
        ),
    )
    monkeypatch.setattr(module, "_audio_service", audio_service)

    with pytest.raises(module.ProviderError, match="Provider failed paragraph audio generation"):
        _invoke_task(run_id=106, section_id="hook-3")

    assert lock_calls == ["para-106-hook-3"]
    assert release_calls == ["para-106-hook-3"]
    assert audio_service.calls == []


def test_generate_paragraph_audio_sanitizes_section_id(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    audio_service = FakeAudioService(artifact_id=78)
    monkeypatch.setattr(
        module,
        "_run_service",
        FakeRunService(
            {
                "current_stage": "AUDIO_GENERATING",
            }
        ),
    )
    monkeypatch.setattr(
        module,
        "_script_service",
        FakeScriptService(
            FakeDraft(structured_script=[FakeSection(section_id="hook:1", text="Sanitize me")])
        ),
    )
    monkeypatch.setattr(module, "_audio_service", audio_service)
    monkeypatch.setattr(module, "sanitize_path_component", lambda value, label: f"san-{value}")

    result = _invoke_task(run_id=107, section_id="hook:1")

    assert result["status"] == "success"
    assert result["audio_path"] == "data/artifacts/107/audio/san-hook:1.wav"
    params = provider.calls[0][2]
    assert params is not None
    assert params["output_path"] == "data/artifacts/107/audio/san-hook:1.wav"
    assert audio_service.calls[0]["path"] == "data/artifacts/107/audio/san-hook:1.wav"


def test_generate_paragraph_audio_section_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    monkeypatch.setattr(
        module, "_run_service", FakeRunService({"current_stage": "AUDIO_GENERATING"})
    )
    monkeypatch.setattr(
        module, "_script_service", FakeScriptService(FakeDraft(structured_script=[]))
    )
    monkeypatch.setattr(module, "_audio_service", FakeAudioService())

    with pytest.raises(ValueError, match="Section 'missing' not found"):
        _invoke_task(run_id=108, section_id="missing")

    assert provider.calls == []


def test_generate_paragraph_audio_rejects_when_run_stage_is_not_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    audio_service = FakeAudioService(artifact_id=79)
    monkeypatch.setattr(
        module,
        "_run_service",
        FakeRunService(
            {
                "current_stage": "SCRIPT_REVIEW",
            }
        ),
    )
    monkeypatch.setattr(
        module,
        "_script_service",
        FakeScriptService(
            FakeDraft(structured_script=[FakeSection(section_id="hook-9", text="Nested paragraph")])
        ),
    )
    monkeypatch.setattr(module, "_audio_service", audio_service)

    with pytest.raises(
        module._task_runner.StageGuardError, match="Run 109 is in stage SCRIPT_REVIEW"
    ):
        _invoke_task(run_id=109, section_id="hook-9")


def test_generate_paragraph_audio_uses_active_draft_not_run_script_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    script_service = FakeScriptService(
        FakeDraft(
            structured_script=[
                FakeSection(section_id="hook-10", text="Text from active draft"),
            ]
        )
    )
    monkeypatch.setattr(module, "_script_service", script_service)
    monkeypatch.setattr(
        module,
        "_run_service",
        FakeRunService(
            {
                "current_stage": "AUDIO_GENERATING",
                "script_data": {
                    "sections": [
                        {"section_id": "hook-10", "text": "Text from run.script_data"},
                    ]
                },
            }
        ),
    )
    monkeypatch.setattr(module, "_audio_service", FakeAudioService(artifact_id=88))

    result = _invoke_task(run_id=110, section_id="hook-10")

    assert result["status"] == "success"
    assert provider.calls[0][0] == "Text from active draft"
    assert script_service.calls == [110]
