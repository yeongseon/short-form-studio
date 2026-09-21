"""SF-23: render source-video segments (trims, fit, audio policy) to a clip that
matches RenderPlan geometry, verified with real FFmpeg.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from creator_domain.models import (
    EncodingProfile,
    OutputSpec,
    RenderPlan,
    RenderSegment,
    RenderSegmentKind,
)
from creator_service.render_segments import (
    SegmentSourceError,
    render_profile_from_plan,
    render_video_segment,
)

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)


def _make_source_video(
    path: Path, seconds: float = 5.0, width: int = 320, height: int = 240, with_audio: bool = True
) -> None:
    cmd = ["ffmpeg", "-y", "-nostdin", "-f", "lavfi", "-i",
           f"testsrc=size={width}x{height}:rate=25:duration={seconds}"]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p"]
    if with_audio:
        cmd += ["-shortest"]
    cmd += [str(path)]
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr


def _probe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


def _plan(output: OutputSpec) -> RenderPlan:
    return RenderPlan.model_validate(
        {
            "segments": [
                {
                    "kind": RenderSegmentKind.IMAGE,
                    "source": "x.png",
                    "timeline_start_seconds": 0.0,
                    "duration_seconds": 1.0,
                }
            ],
            "output_spec": output,
            "encoding_profile": EncodingProfile.preview(),
        }
    )


def _video_segment(source: str, dur: float, **overrides: object) -> RenderSegment:
    payload: dict[str, object] = {
        "kind": RenderSegmentKind.VIDEO,
        "source": source,
        "timeline_start_seconds": 0.0,
        "duration_seconds": dur,
    }
    payload.update(overrides)
    return RenderSegment.model_validate(payload)


def test_render_video_segment_output_dimensions(tmp_path) -> None:
    src = tmp_path / "src.mp4"
    _make_source_video(src, seconds=5.0)
    profile = render_profile_from_plan(_plan(OutputSpec.short_square()))

    out = tmp_path / "seg.ts"
    render_video_segment(_video_segment(str(src), 2.0), out, profile=profile)

    stream = next(s for s in _probe(out)["streams"] if s.get("codec_type") == "video")
    assert (stream["width"], stream["height"]) == (1080, 1080)


def test_render_video_segment_applies_trim_duration(tmp_path) -> None:
    src = tmp_path / "src.mp4"
    _make_source_video(src, seconds=6.0)
    profile = render_profile_from_plan(_plan(OutputSpec.short_vertical()))

    out = tmp_path / "seg.ts"
    render_video_segment(
        _video_segment(str(src), 2.0, trim_start_seconds=1.0, trim_end_seconds=3.0),
        out,
        profile=profile,
    )

    duration = float(_probe(out)["format"]["duration"])
    assert duration == pytest.approx(2.0, abs=0.3)


def test_render_video_segment_rejects_missing_source(tmp_path) -> None:
    profile = render_profile_from_plan(_plan(OutputSpec.short_vertical()))
    with pytest.raises(SegmentSourceError):
        render_video_segment(
            _video_segment(str(tmp_path / "nope.mp4"), 2.0), tmp_path / "seg.ts", profile=profile
        )


def test_render_video_segment_rejects_trim_beyond_source(tmp_path) -> None:
    src = tmp_path / "src.mp4"
    _make_source_video(src, seconds=2.0)
    profile = render_profile_from_plan(_plan(OutputSpec.short_vertical()))
    with pytest.raises(SegmentSourceError):
        render_video_segment(
            _video_segment(str(src), 5.0, trim_start_seconds=1.0, trim_end_seconds=10.0),
            tmp_path / "seg.ts",
            profile=profile,
        )


def test_render_video_segment_without_audio_stream(tmp_path) -> None:
    # A source with no audio must still render video (explicit audio policy:
    # missing audio is not an error).
    src = tmp_path / "silent.mp4"
    _make_source_video(src, seconds=4.0, with_audio=False)
    profile = render_profile_from_plan(_plan(OutputSpec.short_square()))

    out = tmp_path / "seg.ts"
    render_video_segment(_video_segment(str(src), 2.0), out, profile=profile)

    assert out.exists() and out.stat().st_size > 0


def test_render_video_segment_rejects_malformed_media(tmp_path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    profile = render_profile_from_plan(_plan(OutputSpec.short_vertical()))
    with pytest.raises(SegmentSourceError):
        render_video_segment(_video_segment(str(bad), 2.0), tmp_path / "seg.ts", profile=profile)


def test_render_video_segment_rejects_image_kind(tmp_path) -> None:
    profile = render_profile_from_plan(_plan(OutputSpec.short_vertical()))
    image = RenderSegment.model_validate(
        {
            "kind": RenderSegmentKind.IMAGE,
            "source": "a.png",
            "timeline_start_seconds": 0.0,
            "duration_seconds": 2.0,
        }
    )
    with pytest.raises(ValueError):
        render_video_segment(image, tmp_path / "seg.ts", profile=profile)
