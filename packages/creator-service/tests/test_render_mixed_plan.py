"""SF-24: render mixed image + video plans by rendering each segment to a .ts
clip and concatenating them in timeline order, verified with real FFmpeg.
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
    RenderSegmentKind,
)
from creator_service.render_segments import render_plan

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)


def _make_image(path: Path, width: int = 320, height: int = 240, color: str = "red") -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-f", "lavfi", "-i",
         f"color=c={color}:size={width}x{height}:duration=1", "-frames:v", "1", str(path)],
        capture_output=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr


def _make_video(path: Path, seconds: float = 5.0, width: int = 320, height: int = 240) -> None:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-nostdin", "-f", "lavfi", "-i",
         f"testsrc=size={width}x{height}:rate=25:duration={seconds}", "-pix_fmt", "yuv420p",
         str(path)],
        capture_output=True, timeout=60,
    )
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


def _video_stream(meta: dict[str, Any]) -> dict[str, Any]:
    streams: list[dict[str, Any]] = meta.get("streams") or []
    return next(s for s in streams if s.get("codec_type") == "video")


def _plan(segments: list[dict[str, object]], output: OutputSpec) -> RenderPlan:
    return RenderPlan.model_validate(
        {
            "segments": segments,
            "output_spec": output,
            "encoding_profile": EncodingProfile.preview(),
        }
    )


def test_render_plan_mixed_image_and_video(tmp_path) -> None:
    img = tmp_path / "a.png"
    vid = tmp_path / "b.mp4"
    _make_image(img)
    _make_video(vid, seconds=5.0)
    plan = _plan(
        [
            {"kind": RenderSegmentKind.IMAGE, "source": str(img),
             "timeline_start_seconds": 0.0, "duration_seconds": 2.0},
            {"kind": RenderSegmentKind.VIDEO, "source": str(vid),
             "timeline_start_seconds": 2.0, "duration_seconds": 3.0,
             "trim_start_seconds": 0.0, "trim_end_seconds": 3.0},
        ],
        OutputSpec.short_vertical(),
    )

    out = tmp_path / "out.mp4"
    render_plan(plan, out)

    meta = _probe(out)
    duration = float(meta["format"]["duration"])
    assert duration == pytest.approx(5.0, abs=0.4)
    stream = _video_stream(meta)
    assert (stream["width"], stream["height"]) == (1080, 1920)


def test_render_plan_preserves_image_only(tmp_path) -> None:
    img1 = tmp_path / "a.png"
    img2 = tmp_path / "b.png"
    _make_image(img1, color="red")
    _make_image(img2, color="blue")
    plan = _plan(
        [
            {"kind": RenderSegmentKind.IMAGE, "source": str(img1),
             "timeline_start_seconds": 0.0, "duration_seconds": 1.5},
            {"kind": RenderSegmentKind.IMAGE, "source": str(img2),
             "timeline_start_seconds": 1.5, "duration_seconds": 1.5},
        ],
        OutputSpec.short_square(),
    )

    out = tmp_path / "out.mp4"
    render_plan(plan, out)

    meta = _probe(out)
    assert float(meta["format"]["duration"]) == pytest.approx(3.0, abs=0.4)
    stream = _video_stream(meta)
    assert (stream["width"], stream["height"]) == (1080, 1080)


def test_render_plan_video_only(tmp_path) -> None:
    vid = tmp_path / "b.mp4"
    _make_video(vid, seconds=6.0)
    plan = _plan(
        [
            {"kind": RenderSegmentKind.VIDEO, "source": str(vid),
             "timeline_start_seconds": 0.0, "duration_seconds": 2.0,
             "trim_start_seconds": 1.0, "trim_end_seconds": 3.0},
        ],
        OutputSpec.short_vertical(),
    )
    out = tmp_path / "out.mp4"
    render_plan(plan, out)
    assert float(_probe(out)["format"]["duration"]) == pytest.approx(2.0, abs=0.4)


def test_render_plan_rejects_empty(tmp_path) -> None:
    # RenderPlan itself forbids an empty segment list, so a zero-segment plan is
    # unrepresentable — the guard lives at the domain boundary.
    with pytest.raises(ValueError):
        _plan([], OutputSpec.short_vertical())


def test_render_plan_propagates_missing_source(tmp_path) -> None:
    from creator_service.render_segments import SegmentSourceError

    plan = _plan(
        [
            {"kind": RenderSegmentKind.VIDEO, "source": str(tmp_path / "nope.mp4"),
             "timeline_start_seconds": 0.0, "duration_seconds": 2.0},
        ],
        OutputSpec.short_vertical(),
    )
    with pytest.raises(SegmentSourceError):
        render_plan(plan, tmp_path / "out.mp4")
