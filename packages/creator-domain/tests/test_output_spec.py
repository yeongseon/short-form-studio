from __future__ import annotations

import pytest
from creator_domain.models import (
    AspectRatio,
    EncodingProfile,
    OutputSpec,
    VideoCodec,
)


# --- OutputSpec: geometry only ----------------------------------------------


def test_output_spec_holds_geometry() -> None:
    spec = OutputSpec(width=1080, height=1920, fps=30)
    assert spec.width == 1080
    assert spec.height == 1920
    assert spec.fps == 30


def test_output_spec_derives_vertical_aspect_ratio() -> None:
    assert OutputSpec(width=1080, height=1920, fps=30).aspect_ratio is AspectRatio.VERTICAL


def test_output_spec_derives_square_aspect_ratio() -> None:
    assert OutputSpec(width=1080, height=1080, fps=30).aspect_ratio is AspectRatio.SQUARE


def test_output_spec_derives_landscape_aspect_ratio() -> None:
    assert OutputSpec(width=1920, height=1080, fps=30).aspect_ratio is AspectRatio.LANDSCAPE


def test_output_spec_rejects_non_positive_geometry() -> None:
    with pytest.raises(ValueError):
        OutputSpec(width=0, height=1920, fps=30)
    with pytest.raises(ValueError):
        OutputSpec(width=1080, height=0, fps=30)
    with pytest.raises(ValueError):
        OutputSpec(width=1080, height=1920, fps=0)


def test_output_spec_has_no_duration_or_codec_fields() -> None:
    # Geometry only: duration belongs to recipes, codecs to EncodingProfile.
    fields = set(OutputSpec.model_fields)
    assert "min_duration_seconds" not in fields
    assert "max_duration_seconds" not in fields
    assert "crf" not in fields
    assert "video_codec" not in fields


# --- EncodingProfile: codec/quality only ------------------------------------


def test_encoding_profile_preview_preset() -> None:
    profile = EncodingProfile.preview()
    assert profile.name == "preview"
    assert profile.crf > 23  # lower quality / faster
    assert profile.preset in {"veryfast", "ultrafast", "superfast", "faster"}


def test_encoding_profile_standard_preset() -> None:
    profile = EncodingProfile.standard()
    assert profile.name == "standard"
    assert profile.video_codec is VideoCodec.H264


def test_encoding_profile_high_quality_preset() -> None:
    profile = EncodingProfile.high_quality()
    assert profile.name == "high_quality"
    assert profile.crf <= 20
    assert profile.preset in {"slow", "slower", "medium"}


def test_encoding_profile_named_lookup() -> None:
    assert EncodingProfile.by_name("preview").name == "preview"
    assert EncodingProfile.by_name("standard").name == "standard"
    assert EncodingProfile.by_name("high_quality").name == "high_quality"


def test_encoding_profile_rejects_unknown_name() -> None:
    with pytest.raises(ValueError):
        EncodingProfile.by_name("ultra_max")


def test_encoding_profile_has_no_geometry_fields() -> None:
    fields = set(EncodingProfile.model_fields)
    assert "width" not in fields
    assert "height" not in fields
    assert "fps" not in fields


# --- explicit adapter from legacy RenderProfile -----------------------------


def test_output_spec_from_render_profile() -> None:
    from creator_service.render_profile import RenderProfile

    rp = RenderProfile.default()
    spec = OutputSpec.from_render_profile(rp)

    assert spec.width == rp.width
    assert spec.height == rp.height
    assert spec.fps == rp.fps
    assert spec.aspect_ratio is AspectRatio.VERTICAL


def test_encoding_profile_from_render_profile() -> None:
    from creator_service.render_profile import RenderProfile

    rp = RenderProfile.default()
    profile = EncodingProfile.from_render_profile(rp)

    assert profile.crf == rp.crf
    assert profile.preset == rp.preset
    assert profile.video_codec.value == rp.video_codec.value
    assert profile.audio_codec.value == rp.audio_codec.value
