from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tasks import render_video as render_video_module


class FakeStorage:
    def __init__(self, runs: dict[int, dict[str, object]] | None = None) -> None:
        self._runs: dict[int, dict[str, object]] = runs or {}
        self.calls: list[tuple[int, dict[str, object]]] = []
        self.cas_calls: list[tuple[int, dict[str, object], frozenset[str]]] = []

    async def get_run(self, run_id: int) -> dict[str, object] | None:
        return self._runs.get(run_id)

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, object] | None]:
        self.cas_calls.append((run_id, updates, expected_stages))
        row = self._runs.get(run_id)
        if row is None:
            return False, None
        if row.get("current_stage") not in expected_stages:
            return False, dict(row)
        self.calls.append((run_id, updates))
        row.update(updates)
        self._runs[run_id] = row
        return True, dict(row)


def _make_storage(run_id: int = 201, stage: str = "RENDER_GENERATING") -> FakeStorage:
    run_row: dict[str, object] = {"id": run_id, "current_stage": stage}
    return FakeStorage(runs={run_id: run_row})


@dataclass
class FakeVisualAsset:
    scene_id: str
    asset_path: str
    prompt_snapshot: str
    is_active: bool


class FakeVisualAssetService:
    def __init__(self, grouped_assets: dict[str, list[FakeVisualAsset]] | None = None) -> None:
        self.grouped_assets = grouped_assets or {}

    async def list_by_run(self, _run_id: int) -> dict[str, list[FakeVisualAsset]]:
        return self.grouped_assets


@dataclass
class FakeAudioArtifact:
    path: str


class FakeAudioService:
    def __init__(self, artifact: FakeAudioArtifact | None = None) -> None:
        self.artifact = artifact

    async def get_latest(self, _run_id: int) -> FakeAudioArtifact | None:
        return self.artifact


@dataclass
class FakeSubtitleArtifact:
    path: str


class FakeSubtitleService:
    def __init__(self, artifact: FakeSubtitleArtifact | None = None) -> None:
        self.artifact = artifact

    async def get_latest(self, _run_id: int) -> FakeSubtitleArtifact | None:
        return self.artifact


@dataclass
class FakeVideoArtifact:
    id: int
    path: str


class FakeRenderService:
    def __init__(
        self,
        manifest: dict[str, Any],
        artifact_id: int = 1,
        artifact_path: str = "data/artifacts/201/render/output.mp4",
    ) -> None:
        self.manifest = manifest
        self.artifact = FakeVideoArtifact(id=artifact_id, path=artifact_path)
        self.manifest_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    async def build_render_manifest(
        self,
        run_id: int,
        visual_asset_service: Any,
        audio_service: Any,
        subtitle_service: Any,
        render_profile_name: str = "shorts_default",
    ) -> dict[str, Any]:
        self.manifest_calls.append(
            {
                "run_id": run_id,
                "visual_asset_service": visual_asset_service,
                "audio_service": audio_service,
                "subtitle_service": subtitle_service,
                "render_profile_name": render_profile_name,
            }
        )
        return self.manifest

    async def create_artifact(
        self,
        run_id: int,
        path: str,
        *,
        render_profile: str | None = None,
    ) -> FakeVideoArtifact:
        self.create_calls.append(
            {
                "run_id": run_id,
                "path": path,
                "render_profile": render_profile,
            }
        )
        return self.artifact


class FakeFFmpegService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[Any, Path]] = []

    def render(self, render_input: Any, output_path: Path) -> Path:
        self.calls.append((render_input, output_path))
        if self.error is not None:
            raise self.error
        return output_path


def _manifest(
    run_id: int,
    scenes: list[dict[str, object]] | None = None,
    audio_path: str | None = "data/artifacts/201/audio/audio.wav",
    subtitle_path: str | None = "data/artifacts/201/subtitles/subtitles.srt",
    max_duration_seconds: float = 30.0,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "scenes": scenes
        if scenes is not None
        else [
            {"scene_id": "scene-1", "asset_path": "data/artifacts/201/visual/scene-1.png"},
            {"scene_id": "scene-2", "asset_path": "data/artifacts/201/visual/scene-2.png"},
        ],
        "audio_path": audio_path,
        "subtitle_path": subtitle_path,
        "render_profile": {
            "name": "shorts_default",
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "video_codec": "libx264",
            "audio_codec": "aac",
            "transition_style": "none",
            "min_duration_seconds": 10.0,
            "max_duration_seconds": max_duration_seconds,
            "crf": 23,
            "preset": "medium",
            "burn_subtitles": True,
            "subtitle_font_size": 48,
        },
    }


def _patch_services(
    monkeypatch: pytest.MonkeyPatch,
    *,
    storage: FakeStorage,
    fake_render_service: FakeRenderService,
    fake_vas: FakeVisualAssetService,
    fake_audio: FakeAudioService,
    fake_subtitle: FakeSubtitleService,
    fake_ffmpeg: FakeFFmpegService,
) -> None:
    monkeypatch.setattr(render_video_module, "_run_service", SimpleNamespace(storage=storage))
    monkeypatch.setattr(render_video_module, "_render_service", fake_render_service)
    monkeypatch.setattr(render_video_module, "_visual_asset_service", fake_vas)
    monkeypatch.setattr(render_video_module, "_audio_service", fake_audio)
    monkeypatch.setattr(render_video_module, "_subtitle_service", fake_subtitle)
    monkeypatch.setattr(render_video_module, "FFmpegService", lambda: fake_ffmpeg)


def _invoke_task(**kwargs: Any) -> dict[str, object]:
    task = render_video_module.render_video
    run_callable = getattr(task, "run", task)
    return run_callable(**kwargs)


def test_render_video_success(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = 201
    storage = _make_storage(run_id=run_id, stage="RENDER_GENERATING")
    fake_render_service = FakeRenderService(manifest=_manifest(run_id=run_id), artifact_id=77)
    fake_vas = FakeVisualAssetService()
    fake_audio = FakeAudioService()
    fake_subtitle = FakeSubtitleService()
    fake_ffmpeg = FakeFFmpegService()
    _patch_services(
        monkeypatch,
        storage=storage,
        fake_render_service=fake_render_service,
        fake_vas=fake_vas,
        fake_audio=fake_audio,
        fake_subtitle=fake_subtitle,
        fake_ffmpeg=fake_ffmpeg,
    )

    result = _invoke_task(run_id=run_id, render_profile="high_quality")

    assert result["status"] == "success"
    assert result["run_id"] == run_id
    assert result["render_profile"] == "high_quality"
    assert result["video_artifact_id"] == 77
    assert result["video_path"] == "data/artifacts/201/render/output.mp4"
    assert result["scene_count"] == 2
    assert result["audio_path"] == "data/artifacts/201/audio/audio.wav"
    assert result["subtitle_path"] == "data/artifacts/201/subtitles/subtitles.srt"

    assert fake_render_service.manifest_calls[0]["render_profile_name"] == "high_quality"
    assert fake_render_service.create_calls == [
        {
            "run_id": 201,
            "path": "data/artifacts/201/render/output.mp4",
            "render_profile": "high_quality",
        }
    ]

    render_input, output = fake_ffmpeg.calls[0]
    assert output == Path("data/artifacts/201/render/output.mp4")
    assert render_input.image_paths == [
        Path("data/artifacts/201/visual/scene-1.png"),
        Path("data/artifacts/201/visual/scene-2.png"),
    ]
    assert render_input.audio_path == Path("data/artifacts/201/audio/audio.wav")
    assert render_input.subtitle_path == Path("data/artifacts/201/subtitles/subtitles.srt")
    assert render_input.scene_durations == [15.0, 15.0]

    assert storage.calls == [(201, {"current_stage": "FINAL_REVIEW", "status": "running"})]
    assert storage.cas_calls[0][2] == frozenset({"RENDER_GENERATING"})


def test_render_video_run_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = FakeStorage()
    fake_render_service = FakeRenderService(manifest=_manifest(run_id=999))
    fake_vas = FakeVisualAssetService()
    fake_audio = FakeAudioService()
    fake_subtitle = FakeSubtitleService()
    fake_ffmpeg = FakeFFmpegService()
    _patch_services(
        monkeypatch,
        storage=storage,
        fake_render_service=fake_render_service,
        fake_vas=fake_vas,
        fake_audio=fake_audio,
        fake_subtitle=fake_subtitle,
        fake_ffmpeg=fake_ffmpeg,
    )

    with pytest.raises(ValueError, match="Run 999 not found"):
        _invoke_task(run_id=999)

    assert fake_render_service.manifest_calls == []
    assert fake_ffmpeg.calls == []
    assert storage.calls == []


def test_render_video_wrong_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _make_storage(run_id=202, stage="SCRIPT_REVIEW")
    fake_render_service = FakeRenderService(manifest=_manifest(run_id=202))
    fake_vas = FakeVisualAssetService()
    fake_audio = FakeAudioService()
    fake_subtitle = FakeSubtitleService()
    fake_ffmpeg = FakeFFmpegService()
    _patch_services(
        monkeypatch,
        storage=storage,
        fake_render_service=fake_render_service,
        fake_vas=fake_vas,
        fake_audio=fake_audio,
        fake_subtitle=fake_subtitle,
        fake_ffmpeg=fake_ffmpeg,
    )

    with pytest.raises(ValueError, match="expected one of"):
        _invoke_task(run_id=202)

    assert fake_render_service.manifest_calls == []
    assert fake_ffmpeg.calls == []
    assert storage.calls == []


def test_render_video_no_scenes(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _make_storage(run_id=203, stage="RENDER_GENERATING")
    fake_render_service = FakeRenderService(
        manifest=_manifest(run_id=203, scenes=[]),
        artifact_path="data/artifacts/203/render/output.mp4",
    )
    fake_vas = FakeVisualAssetService()
    fake_audio = FakeAudioService()
    fake_subtitle = FakeSubtitleService()
    fake_ffmpeg = FakeFFmpegService()
    _patch_services(
        monkeypatch,
        storage=storage,
        fake_render_service=fake_render_service,
        fake_vas=fake_vas,
        fake_audio=fake_audio,
        fake_subtitle=fake_subtitle,
        fake_ffmpeg=fake_ffmpeg,
    )

    with pytest.raises(RuntimeError, match="No scenes found for render"):
        _invoke_task(run_id=203)

    assert fake_ffmpeg.calls == []
    assert fake_render_service.create_calls == []
    assert storage.calls == [(203, {"current_stage": "FAILED", "status": "failed"})]


def test_render_video_ffmpeg_failure_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _make_storage(run_id=204, stage="RENDER_GENERATING")
    fake_render_service = FakeRenderService(
        manifest=_manifest(run_id=204),
        artifact_path="data/artifacts/204/render/output.mp4",
    )
    fake_vas = FakeVisualAssetService()
    fake_audio = FakeAudioService()
    fake_subtitle = FakeSubtitleService()
    fake_ffmpeg = FakeFFmpegService(error=RuntimeError("ffmpeg crashed"))
    _patch_services(
        monkeypatch,
        storage=storage,
        fake_render_service=fake_render_service,
        fake_vas=fake_vas,
        fake_audio=fake_audio,
        fake_subtitle=fake_subtitle,
        fake_ffmpeg=fake_ffmpeg,
    )

    with pytest.raises(RuntimeError, match="ffmpeg crashed"):
        _invoke_task(run_id=204)

    assert len(fake_ffmpeg.calls) == 1
    assert fake_render_service.create_calls == []
    assert storage.calls == [(204, {"current_stage": "FAILED", "status": "failed"})]
    assert storage.cas_calls[0][2] == frozenset({"RENDER_GENERATING"})


def test_render_video_without_audio_subtitles(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _make_storage(run_id=205, stage="RENDER_GENERATING")
    fake_render_service = FakeRenderService(
        manifest=_manifest(run_id=205, audio_path=None, subtitle_path=None),
        artifact_path="data/artifacts/205/render/output.mp4",
    )
    fake_vas = FakeVisualAssetService()
    fake_audio = FakeAudioService()
    fake_subtitle = FakeSubtitleService()
    fake_ffmpeg = FakeFFmpegService()
    _patch_services(
        monkeypatch,
        storage=storage,
        fake_render_service=fake_render_service,
        fake_vas=fake_vas,
        fake_audio=fake_audio,
        fake_subtitle=fake_subtitle,
        fake_ffmpeg=fake_ffmpeg,
    )

    result = _invoke_task(run_id=205, render_profile="fast_preview")

    assert result["status"] == "success"
    assert result["audio_path"] is None
    assert result["subtitle_path"] is None
    render_input, _ = fake_ffmpeg.calls[0]
    assert render_input.audio_path is None
    assert render_input.subtitle_path is None


class _CASSkipStorage(FakeStorage):
    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        expected_stages: frozenset[str],
    ) -> tuple[bool, dict[str, object] | None]:
        self.cas_calls.append((run_id, updates, expected_stages))
        row = self._runs.get(run_id)
        return False, dict(row) if row else None


def test_render_video_cas_skip_on_stage_change(monkeypatch: pytest.MonkeyPatch) -> None:
    run_row: dict[str, object] = {"id": 206, "current_stage": "RENDER_GENERATING"}
    storage = _CASSkipStorage(runs={206: run_row})
    fake_render_service = FakeRenderService(
        manifest=_manifest(run_id=206),
        artifact_id=90,
        artifact_path="data/artifacts/206/render/output.mp4",
    )
    fake_vas = FakeVisualAssetService()
    fake_audio = FakeAudioService()
    fake_subtitle = FakeSubtitleService()
    fake_ffmpeg = FakeFFmpegService()
    _patch_services(
        monkeypatch,
        storage=storage,
        fake_render_service=fake_render_service,
        fake_vas=fake_vas,
        fake_audio=fake_audio,
        fake_subtitle=fake_subtitle,
        fake_ffmpeg=fake_ffmpeg,
    )

    result = _invoke_task(run_id=206)

    assert result["status"] == "success"
    assert result["video_artifact_id"] == 90
    assert len(fake_ffmpeg.calls) == 1
    assert len(fake_render_service.create_calls) == 1
    assert len(storage.cas_calls) == 1
    assert storage.cas_calls[0][1] == {"current_stage": "FINAL_REVIEW", "status": "running"}
    assert storage.calls == []


def test_render_video_default_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _make_storage(run_id=207, stage="RENDER_GENERATING")
    fake_render_service = FakeRenderService(
        manifest=_manifest(run_id=207),
        artifact_path="data/artifacts/207/render/output.mp4",
    )
    fake_vas = FakeVisualAssetService()
    fake_audio = FakeAudioService()
    fake_subtitle = FakeSubtitleService()
    fake_ffmpeg = FakeFFmpegService()
    _patch_services(
        monkeypatch,
        storage=storage,
        fake_render_service=fake_render_service,
        fake_vas=fake_vas,
        fake_audio=fake_audio,
        fake_subtitle=fake_subtitle,
        fake_ffmpeg=fake_ffmpeg,
    )

    result = _invoke_task(run_id=207)

    assert result["status"] == "success"
    assert result["render_profile"] == "shorts_default"
    assert fake_render_service.manifest_calls[0]["render_profile_name"] == "shorts_default"
    assert fake_render_service.create_calls[0]["render_profile"] == "shorts_default"
