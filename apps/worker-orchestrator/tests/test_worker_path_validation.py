from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from tasks import generate_subtitles as generate_subtitles_module
from tasks import render_video as render_video_module


@dataclass
class _AudioArtifact:
    path: str


@dataclass
class _ScriptDraft:
    markdown_content: str | None = "script"
    structured_script: list[Any] | None = None


class _Provider:
    async def transcribe(self, audio_path: str, params: dict[str, object] | None = None) -> None:
        return None


async def _async_return(value: Any) -> Any:
    return value


class _SubtitleService:
    async def create_artifact(self, **kwargs: Any) -> Any:
        return SimpleNamespace(id=1, path=kwargs["path"])


class _RenderService:
    def __init__(self, manifest: dict[str, Any]) -> None:
        self.manifest = manifest

    async def build_render_manifest(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.manifest

    async def create_artifact(self, **kwargs: Any) -> Any:
        return SimpleNamespace(id=1, path=kwargs["path"])


class _Registry:
    @staticmethod
    def create_default() -> Any:
        return SimpleNamespace(
            resolve=lambda _model: SimpleNamespace(
                provider_type="faster-whisper",
                endpoint="http://whisper:8200",
                requires_gpu=False,
                default_params={},
            ),
            get_provider=lambda _model: _Provider(),
        )


class _Storage:
    def __init__(self, run_id: int, stage: str) -> None:
        self.run = {"id": run_id, "current_stage": stage}

    async def get_run(self, run_id: int) -> dict[str, object] | None:
        return self.run if self.run["id"] == run_id else None

    async def conditional_update_run(
        self, run_id: int, updates: dict[str, object], expected_stages: frozenset[str],
    rejected_statuses: frozenset[str] | None = None,
    ) -> tuple[bool, dict[str, object] | None]:
        if self.run["id"] != run_id or self.run["current_stage"] not in expected_stages:
            return False, self.run
        self.run.update(updates)
        return True, self.run


def test_generate_subtitles_rejects_traversal_audio_artifact_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generate_subtitles_module, "get_default_registry", _Registry.create_default)
    monkeypatch.setattr(
        "tasks.task_runner._run_service",
        SimpleNamespace(storage=_Storage(run_id=311, stage="AUDIO_GENERATING")),
    )
    monkeypatch.setattr(
        generate_subtitles_module,
        "_script_service",
        SimpleNamespace(get_active_draft=lambda _rid: _async_return(_ScriptDraft())),
    )
    monkeypatch.setattr(
        generate_subtitles_module,
        "_audio_service",
        SimpleNamespace(
            get_latest=lambda _rid: _async_return(
                _AudioArtifact(path="data/artifacts/311/../../escape.wav")
            )
        ),
    )
    monkeypatch.setattr(
        generate_subtitles_module,
        "_subtitle_service",
        _SubtitleService(),
    )

    task = generate_subtitles_module.generate_subtitles
    run_callable: Callable[..., dict[str, object]] = getattr(task, "run", task)
    with pytest.raises(RuntimeError, match="audio artifact path"):
        run_callable(run_id=311)


class _FFmpeg:
    def __init__(self, profile: Any = None) -> None:
        self.profile = profile

    def render(self, render_input: Any, output_path: Any) -> Any:
        return output_path


def test_render_video_rejects_traversal_manifest_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = 401
    manifest = {
        "run_id": run_id,
        "scenes": [{"scene_id": "scene-1", "asset_path": "data/artifacts/401/../../escape.png"}],
        "audio_path": "data/artifacts/401/audio/audio.wav",
        "subtitle_path": "data/artifacts/401/subtitles/subtitles.srt",
        "render_profile": {"max_duration_seconds": 30.0},
    }

    monkeypatch.setattr(
        "tasks.task_runner._run_service",
        SimpleNamespace(storage=_Storage(run_id=run_id, stage="RENDER_GENERATING")),
    )
    monkeypatch.setattr(render_video_module, "_render_service", _RenderService(manifest))
    monkeypatch.setattr(render_video_module, "_visual_asset_service", SimpleNamespace())
    monkeypatch.setattr(
        render_video_module,
        "_audio_service",
        SimpleNamespace(list_paragraph_audio=lambda _rid: _async_return([])),
    )
    monkeypatch.setattr(
        render_video_module,
        "_subtitle_service",
        SimpleNamespace(list_paragraph_subtitles=lambda _rid: _async_return([])),
    )
    monkeypatch.setattr(
        render_video_module,
        "_visual_plan_service",
        SimpleNamespace(get_active_plan=lambda _rid: _async_return(None)),
    )
    monkeypatch.setattr(
        render_video_module,
        "_script_service",
        SimpleNamespace(get_active_draft=lambda _rid: _async_return(None)),
    )
    monkeypatch.setattr(render_video_module, "FFmpegService", _FFmpeg)

    task = render_video_module.render_video
    run_callable: Callable[..., dict[str, object]] = getattr(task, "run", task)
    with pytest.raises(RuntimeError, match="manifest path"):
        run_callable(run_id=run_id)


def test_generate_subtitles_rejects_absolute_path_when_artifact_root_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: absolute audio artifact path must be rejected even without ARTIFACT_ROOT."""
    monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
    # Force module to re-evaluate _ARTIFACT_ROOT default
    monkeypatch.setattr(generate_subtitles_module, "_ARTIFACT_ROOT", "data/artifacts")
    monkeypatch.setattr(generate_subtitles_module, "get_default_registry", _Registry.create_default)
    monkeypatch.setattr(
        "tasks.task_runner._run_service",
        SimpleNamespace(storage=_Storage(run_id=500, stage="AUDIO_GENERATING")),
    )
    monkeypatch.setattr(
        generate_subtitles_module,
        "_script_service",
        SimpleNamespace(get_active_draft=lambda _rid: _async_return(_ScriptDraft())),
    )
    monkeypatch.setattr(
        generate_subtitles_module,
        "_audio_service",
        SimpleNamespace(
            get_latest=lambda _rid: _async_return(
                _AudioArtifact(path="/etc/shadow")
            )
        ),
    )
    monkeypatch.setattr(
        generate_subtitles_module,
        "_subtitle_service",
        _SubtitleService(),
    )

    task = generate_subtitles_module.generate_subtitles
    run_callable: Callable[..., dict[str, object]] = getattr(task, "run", task)
    with pytest.raises(RuntimeError, match="audio artifact path"):
        run_callable(run_id=500)


def test_render_video_rejects_absolute_path_when_artifact_root_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: absolute manifest paths must be rejected even without ARTIFACT_ROOT."""
    monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
    monkeypatch.setattr(render_video_module, "_ARTIFACT_ROOT", "data/artifacts")
    run_id = 501
    manifest = {
        "run_id": run_id,
        "scenes": [{"scene_id": "scene-1", "asset_path": "/etc/shadow"}],
        "audio_path": "data/artifacts/501/audio/audio.wav",
        "subtitle_path": "data/artifacts/501/subtitles/subtitles.srt",
        "render_profile": {"max_duration_seconds": 30.0},
    }

    monkeypatch.setattr(
        "tasks.task_runner._run_service",
        SimpleNamespace(storage=_Storage(run_id=run_id, stage="RENDER_GENERATING")),
    )
    monkeypatch.setattr(render_video_module, "_render_service", _RenderService(manifest))
    monkeypatch.setattr(render_video_module, "_visual_asset_service", SimpleNamespace())
    monkeypatch.setattr(
        render_video_module,
        "_audio_service",
        SimpleNamespace(list_paragraph_audio=lambda _rid: _async_return([])),
    )
    monkeypatch.setattr(
        render_video_module,
        "_subtitle_service",
        SimpleNamespace(list_paragraph_subtitles=lambda _rid: _async_return([])),
    )
    monkeypatch.setattr(
        render_video_module,
        "_visual_plan_service",
        SimpleNamespace(get_active_plan=lambda _rid: _async_return(None)),
    )
    monkeypatch.setattr(
        render_video_module,
        "_script_service",
        SimpleNamespace(get_active_draft=lambda _rid: _async_return(None)),
    )
    monkeypatch.setattr(render_video_module, "FFmpegService", _FFmpeg)

    task = render_video_module.render_video
    run_callable: Callable[..., dict[str, object]] = getattr(task, "run", task)
    with pytest.raises(RuntimeError, match="manifest path"):
        run_callable(run_id=run_id)
