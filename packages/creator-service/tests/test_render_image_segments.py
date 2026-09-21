"""SF-22: render image segments through the segment adapter + FFmpeg, verifying
output dimensions/duration from RenderPlan geometry/encoding.
"""

from __future__ import annotations

import io
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
from creator_service.ffmpeg_service import FFmpegService
from creator_service.render_segments import (
    render_input_from_plan,
    render_profile_from_plan,
)
from PIL import Image

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not available",
)


def _write_png(path: Path, width: int = 320, height: int = 240) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (30, 60, 90)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _img_segment(source: str, start: float, dur: float) -> RenderSegment:
    return RenderSegment.model_validate(
        {
            "kind": RenderSegmentKind.IMAGE,
            "source": source,
            "timeline_start_seconds": start,
            "duration_seconds": dur,
        }
    )


def _probe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    result: dict[str, Any] = json.loads(proc.stdout)
    return result


def _video_stream(meta: dict[str, Any]) -> dict[str, Any]:
    streams: list[dict[str, Any]] = meta.get("streams") or []
    return next(s for s in streams if s.get("codec_type") == "video")


# --- render_profile_from_plan bridge ----------------------------------------


def test_render_profile_from_plan_maps_geometry_and_encoding() -> None:
    plan = RenderPlan.model_validate(
        {
            "segments": [_img_segment("a.png", 0.0, 2.0)],
            "output_spec": OutputSpec.short_landscape(),
            "encoding_profile": EncodingProfile.high_quality(),
        }
    )
    profile = render_profile_from_plan(plan)
    assert (profile.width, profile.height) == (1920, 1080)
    assert profile.crf == EncodingProfile.high_quality().crf
    assert profile.preset == EncodingProfile.high_quality().preset


# --- real FFmpeg render, parametrized by geometry ---------------------------


@pytest.mark.parametrize(
    ("preset_factory", "expected"),
    [
        (OutputSpec.short_vertical, (1080, 1920)),
        (OutputSpec.short_square, (1080, 1080)),
        (OutputSpec.short_landscape, (1920, 1080)),
    ],
)
def test_render_image_segments_output_dimensions(tmp_path, preset_factory, expected) -> None:
    img1 = tmp_path / "s1.png"
    img2 = tmp_path / "s2.png"
    _write_png(img1)
    _write_png(img2)

    plan = RenderPlan.model_validate(
        {
            "segments": [
                _img_segment(str(img1), 0.0, 1.0),
                _img_segment(str(img2), 1.0, 1.0),
            ],
            "output_spec": preset_factory(),
            # preview keeps the fixture fast
            "encoding_profile": EncodingProfile.preview(),
        }
    )

    service = FFmpegService(profile=render_profile_from_plan(plan))
    render_input = render_input_from_plan(plan)
    output = tmp_path / "out.mp4"

    result = service.render(render_input, output)

    assert result == output
    assert output.exists() and output.stat().st_size > 0
    stream = _video_stream(_probe(output))
    assert (stream["width"], stream["height"]) == expected


def test_render_multiple_image_segments_total_duration(tmp_path) -> None:
    images = []
    for i in range(3):
        p = tmp_path / f"s{i}.png"
        _write_png(p)
        images.append(p)

    plan = RenderPlan.model_validate(
        {
            "segments": [
                _img_segment(str(images[0]), 0.0, 1.0),
                _img_segment(str(images[1]), 1.0, 1.0),
                _img_segment(str(images[2]), 2.0, 1.0),
            ],
            "output_spec": OutputSpec.short_square(),
            "encoding_profile": EncodingProfile.preview(),
        }
    )

    service = FFmpegService(profile=render_profile_from_plan(plan))
    output = tmp_path / "out.mp4"
    service.render(render_input_from_plan(plan), output)

    meta = _probe(output)
    duration = float((meta.get("format") or {}).get("duration"))
    assert duration == pytest.approx(3.0, abs=0.35)


def test_render_rejects_missing_asset(tmp_path) -> None:
    plan = RenderPlan.model_validate(
        {
            "segments": [_img_segment(str(tmp_path / "does_not_exist.png"), 0.0, 1.0)],
            "output_spec": OutputSpec.short_vertical(),
            "encoding_profile": EncodingProfile.preview(),
        }
    )
    service = FFmpegService(profile=render_profile_from_plan(plan))
    with pytest.raises(Exception):
        service.render(render_input_from_plan(plan), tmp_path / "out.mp4")
