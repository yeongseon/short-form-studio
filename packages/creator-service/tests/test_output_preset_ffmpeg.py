from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from typing import Annotated, Final, Literal

import pytest
from creator_domain.models import EncodingProfile, OutputSpec, RenderPlan, RenderSegment
from creator_domain.models.render_segment import RenderSegmentKind
from creator_service.ffmpeg_service import FFmpegService
from creator_service.render_segments import render_input_from_plan, render_profile_from_plan
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)

_DURATION: Final = 0.4
_SAMPLE_RATE: Final = 48000


class _VideoStream(BaseModel):
    model_config = ConfigDict(frozen=True)

    codec_type: Literal["video"]
    codec_name: str
    width: int
    height: int
    sample_aspect_ratio: str
    display_aspect_ratio: str
    r_frame_rate: str
    pix_fmt: str


class _AudioStream(BaseModel):
    model_config = ConfigDict(frozen=True)

    codec_type: Literal["audio"]
    codec_name: str


class _Format(BaseModel):
    model_config = ConfigDict(frozen=True)

    duration: float


class _Probe(BaseModel):
    model_config = ConfigDict(frozen=True)

    streams: tuple[Annotated[_VideoStream | _AudioStream, Field(discriminator="codec_type")], ...]
    format: _Format


@pytest.mark.parametrize(
    "output_case",
    [
        pytest.param(("short_square", 1080, 1080, "1:1"), id="short_square"),
        pytest.param(("short_landscape", 1920, 1080, "16:9"), id="short_landscape"),
    ],
)
@pytest.mark.parametrize(
    "encoding_case",
    [
        pytest.param(("preview", 28, "veryfast"), id="preview"),
        pytest.param(("standard", 23, "fast"), id="standard"),
        pytest.param(("high_quality", 18, "slow"), id="high_quality"),
    ],
)
def test_output_preset_renders_with_each_encoding_profile(
    tmp_path: Path,
    output_case: tuple[str, int, int, str],
    encoding_case: tuple[str, int, str],
) -> None:
    # Given: registered geometry/encoding presets and 0.4 seconds of local media.
    preset_name, width, height, aspect = output_case
    encoding_name, crf, encoder_preset = encoding_case
    image_path = tmp_path / "still.png"
    with Image.new("RGB", (64, 48), (30, 60, 90)) as image:
        image.save(image_path)
    audio_path = tmp_path / "silence.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(_SAMPLE_RATE)
        audio.writeframes(b"\x00\x00" * int(_SAMPLE_RATE * _DURATION))
    plan = RenderPlan(
        segments=[
            RenderSegment(
                kind=RenderSegmentKind.IMAGE,
                source=str(image_path),
                timeline_start_seconds=0.0,
                duration_seconds=_DURATION,
            ),
        ],
        output_spec=OutputSpec.preset(preset_name),
        encoding_profile=EncodingProfile.by_name(encoding_name),
    )
    output_path = tmp_path / f"{preset_name}-{encoding_name}.mp4"

    # When: production adapters and renderer encode the generic RenderPlan.
    profile = render_profile_from_plan(plan)
    result = FFmpegService(profile=profile).render(
        render_input_from_plan(plan, audio_path=audio_path),
        output_path,
    )

    # Then: the adapter preserves quality and the real artifact meets the preset AC.
    assert (profile.name, profile.crf, profile.preset) == (encoding_name, crf, encoder_preset)
    assert (profile.video_codec.value, profile.audio_codec.value) == ("libx264", "aac")
    assert profile.fps == 30
    assert plan.output_spec.aspect_ratio.value == aspect
    assert result == output_path
    probe_result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(result),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    probe = _Probe.model_validate_json(probe_result.stdout)
    assert len(probe.streams) == 2
    video = next(stream for stream in probe.streams if stream.codec_type == "video")
    sound = next(stream for stream in probe.streams if stream.codec_type == "audio")
    assert (video.width, video.height) == (width, height)
    assert video.display_aspect_ratio == aspect
    assert video.sample_aspect_ratio == "1:1"
    assert video.r_frame_rate == "30/1"
    assert video.pix_fmt == "yuv420p"
    assert (video.codec_name, sound.codec_name) == ("h264", "aac")
    assert probe.format.duration == pytest.approx(_DURATION, abs=1 / 30)
