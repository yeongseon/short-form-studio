from pathlib import Path

import pytest
from creator_domain.models import ScriptSection
from creator_service.audio_service import AudioService
from creator_service.ffmpeg_service import FFmpegService
from creator_service.render_service import RenderService
from creator_service.script_service import ScriptService
from creator_service.subtitle_service import SubtitleService
from creator_service.visual_asset_service import VisualAssetService
from creator_service.visual_plan_service import VisualPlanService
from tasks.legacy_render_audio import prepare_audio
from tasks.legacy_render_contract import LegacyManifest, LegacyRequest, LegacyServices


class RecordingFFmpeg(FFmpegService):
    def __init__(self) -> None:
        super().__init__()
        self.audio_order: list[str] = []
        self.subtitle_order: list[str] = []
        self.subtitle_durations: list[float] = []

    def get_audio_duration(self, audio_path: str) -> float:
        return 3.0 if "second" in audio_path else 2.0

    def concatenate_audio(self, audio_paths: list[str], output_path: str) -> Path:
        self.audio_order = audio_paths
        return Path(output_path)

    def merge_subtitles(self, subtitle_paths: list[str], durations: list[float], output_path: str) -> Path:
        self.subtitle_order = subtitle_paths
        self.subtitle_durations = durations
        return Path(output_path)


@pytest.mark.asyncio
async def test_paragraph_audio_preserves_script_order_and_first_returned_section(tmp_path: Path) -> None:
    audio, subtitles, scripts = AudioService(), SubtitleService(), ScriptService()
    await scripts.save_draft(1, "pasted_json", structured_script=[
        ScriptSection(section_id="second", type="body", text="Second"),
        ScriptSection(section_id="first", type="hook", text="First"),
    ])
    for name in ("second", "first"):
        await audio.create_paragraph_artifact(1, name, str(tmp_path / f"{name}-old.wav"))
        await audio.create_paragraph_artifact(1, name, str(tmp_path / f"{name}.wav"))
        await subtitles.create_paragraph_artifact(1, name, str(tmp_path / f"{name}.srt"))
    ffmpeg = RecordingFFmpeg()
    services = LegacyServices(
        RenderService(), VisualAssetService(), audio, subtitles,
        VisualPlanService(), scripts, FFmpegService,
    )
    manifest = LegacyManifest.model_validate({
        "scenes": [{"scene_id": name, "asset_path": str(tmp_path / f"{name}.png")} for name in ("a", "b", "c")],
        "audio_path": None, "subtitle_path": None, "render_profile": {"max_duration_seconds": 60},
    })
    result = await prepare_audio(LegacyRequest(1, "fast_preview", str(tmp_path)), services, manifest, ffmpeg=ffmpeg)
    assert ffmpeg.audio_order == [str(tmp_path / "second-old.wav"), str(tmp_path / "first-old.wav")]
    assert result.durations == [3.0, 2.0, 5.0]
    assert ffmpeg.subtitle_order == [str(tmp_path / "second.srt"), str(tmp_path / "first.srt")]
    assert ffmpeg.subtitle_durations == [3.0, 2.0]
    assert result.subtitles == tmp_path / "1/render/subtitles_merged.srt"
