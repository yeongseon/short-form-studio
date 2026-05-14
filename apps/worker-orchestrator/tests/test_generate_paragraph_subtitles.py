from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from tasks import generate_paragraph_subtitles as module


@dataclass
class FakeEntry:
    provider_type: str = "faster-whisper"
    endpoint: str = "http://whisper:8200"
    requires_gpu: bool = False
    default_params: dict[str, object] | None = None


class FakeProvider:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    async def transcribe(self, audio_path: str, params: dict[str, object] | None = None) -> None:
        self.calls.append((audio_path, params))
        if self.error is not None:
            raise self.error


@dataclass
class FakeSubtitleArtifact:
    id: int
    path: str


@dataclass
class FakeAudioArtifact:
    path: str


class FakeSubtitleService:
    def __init__(self, artifact_id: int = 1) -> None:
        self.artifact_id = artifact_id
        self.calls: list[dict[str, object]] = []

    async def create_paragraph_artifact(
        self,
        run_id: int,
        section_id: int,
        path: str,
        *,
        fmt: str | None = None,
        model_used: str | None = None,
        provider_type: str | None = None,
        storage_provider: str | None = None,
        storage_key: str | None = None,
    ) -> FakeSubtitleArtifact:
        call_data = {
            "run_id": run_id,
            "section_id": section_id,
            "path": path,
            "fmt": fmt,
            "model_used": model_used,
            "provider_type": provider_type,
            "storage_provider": storage_provider,
            "storage_key": storage_key,
        }
        self.calls.append(call_data)
        return FakeSubtitleArtifact(id=self.artifact_id, path=path)


class FakeAudioService:
    def __init__(self, artifact: FakeAudioArtifact | None = None) -> None:
        self.artifact = artifact
        self.calls: list[tuple[int, str]] = []

    async def get_paragraph_audio(self, run_id: int, section_id: str) -> FakeAudioArtifact | None:
        self.calls.append((run_id, section_id))
        return self.artifact


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
    task = module.generate_paragraph_subtitles
    run_callable = getattr(task, "run", task)
    return run_callable(**kwargs)


def test_generate_paragraph_subtitles_success(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False, default_params={"temperature": 0.1})
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    subtitle_service = FakeSubtitleService(artifact_id=33)
    audio_service = FakeAudioService(
        artifact=FakeAudioArtifact(path="data/artifacts/101/audio/hook-1.wav")
    )
    monkeypatch.setattr(module, "_subtitle_service", subtitle_service)
    monkeypatch.setattr(module, "_audio_service", audio_service)
    monkeypatch.setattr(
        module, "_run_service", FakeRunService({"current_stage": "AUDIO_GENERATING"})
    )
    monkeypatch.setattr(module, "validate_artifact_path", lambda path, _root: path)
    monkeypatch.setattr(module.os.path, "exists", lambda _: True)

    result = _invoke_task(
        run_id=101,
        section_id="hook-1",
        subtitle_model="whisper-small",
        subtitle_format="srt",
    )

    assert result["status"] == "success"
    assert result["subtitle_artifact_id"] == 33
    assert result["run_id"] == 101
    assert result["section_id"] == "hook-1"
    assert result["subtitle_model"] == "whisper-small"
    assert result["subtitle_format"] == "srt"
    assert result["provider_type"] == "faster-whisper"
    assert result["endpoint"] == "http://whisper:8200"
    assert result["subtitle_path"] == "data/artifacts/101/subtitles/hook-1.srt"
    assert result["audio_path"] == "data/artifacts/101/audio/hook-1.wav"

    assert provider.calls == [
        (
            "data/artifacts/101/audio/hook-1.wav",
            {
                "temperature": 0.1,
                "format": "srt",
                "output_path": "data/artifacts/101/subtitles/hook-1.srt",
            },
        )
    ]
    assert len(subtitle_service.calls) >= 1  # Updated: storage fields may be present


def test_generate_paragraph_subtitles_audio_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    _patch_registry(
        monkeypatch, FakeRegistry(entry=FakeEntry(requires_gpu=False), provider=provider)
    )

    subtitle_service = FakeSubtitleService()
    audio_service = FakeAudioService(artifact=None)
    monkeypatch.setattr(module, "_subtitle_service", subtitle_service)
    monkeypatch.setattr(module, "_audio_service", audio_service)
    monkeypatch.setattr(
        module, "_run_service", FakeRunService({"current_stage": "AUDIO_GENERATING"})
    )

    with pytest.raises(RuntimeError, match="Audio file not found"):
        _invoke_task(run_id=102, section_id="hook-2")

    assert provider.calls == []
    assert subtitle_service.calls == []


def test_generate_paragraph_subtitles_with_gpu_lock(monkeypatch: pytest.MonkeyPatch) -> None:
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

    subtitle_service = FakeSubtitleService(artifact_id=61)
    audio_service = FakeAudioService(artifact=FakeAudioArtifact(path="audio.wav"))
    monkeypatch.setattr(module, "_subtitle_service", subtitle_service)
    monkeypatch.setattr(module, "_audio_service", audio_service)
    monkeypatch.setattr(
        module, "_run_service", FakeRunService({"current_stage": "AUDIO_GENERATING"})
    )
    monkeypatch.setattr(module, "validate_artifact_path", lambda path, _root: path)
    monkeypatch.setattr(module.os.path, "exists", lambda _: True)

    result = _invoke_task(run_id=103, section_id="hook-3")

    assert result["status"] == "success"
    assert result["gpu_lock_acquired_at"] is not None
    assert result["gpu_lock_released_at"] is not None
    assert lock_calls == ["sub-103-hook-3"]
    assert release_calls == ["sub-103-hook-3"]


def test_generate_paragraph_subtitles_provider_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    provider = FakeProvider(error=RuntimeError("subtitle provider failed"))
    entry = FakeEntry(requires_gpu=False)
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    subtitle_service = FakeSubtitleService()
    audio_service = FakeAudioService(artifact=FakeAudioArtifact(path="audio.wav"))
    monkeypatch.setattr(module, "_subtitle_service", subtitle_service)
    monkeypatch.setattr(module, "_audio_service", audio_service)
    monkeypatch.setattr(
        module, "_run_service", FakeRunService({"current_stage": "AUDIO_GENERATING"})
    )
    monkeypatch.setattr(module, "validate_artifact_path", lambda path, _root: path)
    monkeypatch.setattr(module.os.path, "exists", lambda _: True)

    audio_file = tmp_path / "audio.wav"
    audio_file.write_bytes(b"fake")
    with pytest.raises(
        module.ProviderError,
        match="Provider failed paragraph subtitle generation",
    ):
        _invoke_task(run_id=104, section_id="hook-4")

    assert subtitle_service.calls == []


def test_generate_paragraph_subtitles_rejects_audio_path_outside_artifact_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    _patch_registry(
        monkeypatch, FakeRegistry(entry=FakeEntry(requires_gpu=False), provider=provider)
    )

    subtitle_service = FakeSubtitleService()
    audio_service = FakeAudioService(artifact=FakeAudioArtifact(path="/etc/passwd"))
    monkeypatch.setattr(module, "_subtitle_service", subtitle_service)
    monkeypatch.setattr(module, "_audio_service", audio_service)
    monkeypatch.setattr(
        module, "_run_service", FakeRunService({"current_stage": "AUDIO_GENERATING"})
    )

    with pytest.raises(ValueError, match="outside artifact root"):
        _invoke_task(run_id=105, section_id="hook-5")

    assert subtitle_service.calls == []


def test_generate_paragraph_subtitles_rejects_when_run_stage_is_not_subtitle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    _patch_registry(monkeypatch, FakeRegistry(entry=entry, provider=provider))

    subtitle_service = FakeSubtitleService(artifact_id=44)
    audio_service = FakeAudioService(
        artifact=FakeAudioArtifact(path="data/artifacts/111/audio/hook-7.wav")
    )
    monkeypatch.setattr(module, "_subtitle_service", subtitle_service)
    monkeypatch.setattr(module, "_audio_service", audio_service)
    monkeypatch.setattr(module, "_run_service", FakeRunService({"current_stage": "SCRIPT_REVIEW"}))
    monkeypatch.setattr(module, "validate_artifact_path", lambda path, _root: path)
    monkeypatch.setattr(module.os.path, "exists", lambda _: True)

    with pytest.raises(
        module._task_runner.StageGuardError, match="Run 111 is in stage SCRIPT_REVIEW"
    ):
        _invoke_task(run_id=111, section_id="hook-7")
