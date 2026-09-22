import subprocess
from pathlib import Path

import anyio
import pytest
from PIL import Image
from creator_service.audio_service import AudioService
from creator_service.script_service import ScriptService
from creator_service.subtitle_service import SubtitleService
from creator_service.visual_asset_service import VisualAssetService
from creator_service.visual_plan_service import VisualPlanService
from tasks import render_video
from tests.test_timeline_worker import WorkerFixture, worker as worker


def test_legacy_worker_renders_bgm_and_styled_subtitles(worker: WorkerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = AudioService()
    subtitles = SubtitleService()
    visuals = VisualAssetService()
    monkeypatch.setattr(render_video, "_audio_service", audio)
    monkeypatch.setattr(render_video, "_subtitle_service", subtitles)
    monkeypatch.setattr(render_video, "_visual_asset_service", visuals)
    monkeypatch.setattr(render_video, "_visual_plan_service", VisualPlanService())
    monkeypatch.setattr(render_video, "_script_service", ScriptService())
    image = worker.root / "scene.png"
    Image.new("RGB", (96, 160), "red").save(image)
    voice = worker.root / "voice.wav"
    subtitle = worker.root / "captions.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nLEGACY CAPTION\n")
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1", str(voice),
    ], check=True, capture_output=True, timeout=30)

    async def seed() -> int:
        row = await worker.runs.create_run({
            "project_id": 11, "current_stage": "RENDER_GENERATING", "status": "running",
        })
        run_id = int(row["id"])
        await visuals.create_asset(run_id, "scene", str(image))
        await audio.create_artifact(run_id, str(voice))
        await subtitles.create_artifact(run_id, str(subtitle))
        return run_id

    run_id = anyio.run(seed)
    result = render_video.render_video.run(run_id=run_id, render_profile="fast_preview")
    assert result["status"] == "success"
    assert Path(str(result["audio_path"])).name == "audio_normalized.mp3"
    assert Path(str(result["subtitle_path"])).suffix == ".ass"
    output = Path(str(result["video_path"]))
    assert (output.parent / "bgm.mp3").is_file()
    assert (output.parent / "audio_sfx.mp3").is_file()
    streams = subprocess.run([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(output),
    ], check=True, capture_output=True, text=True, timeout=30).stdout
    assert "h264" in streams and "aac" in streams
    row = anyio.run(worker.runs.get_run, run_id)
    assert row is not None and row["current_stage"] == "FINAL_REVIEW"
