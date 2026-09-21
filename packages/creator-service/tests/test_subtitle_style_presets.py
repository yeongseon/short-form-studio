"""SF-66: reusable subtitle-style presets shared by Preview and the renderer.

Presets are named, validated SubtitleStyle instances over the SF-61 output-relative
ratio model — no new subtitle-style fields and no duplicated ASS logic. Selecting a
preset reuses the SF-61 undo history, and the SAME resolved style feeds both the
preview and the renderer helpers, so a preset renders legibly and identically
across output ratios. CJK legibility comes from the renderer's existing
NanumGothic ASS default, which these tests characterize (font name + threaded font
size) rather than re-specifying.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_service.ffmpeg_service import FFmpegService
from creator_service.subtitle_style import (
    DEFAULT_FONT_SIZE_RATIO,
    FONT_SIZE_TIERS,
    MAX_FONT_SIZE_RATIO,
    MIN_FONT_SIZE_RATIO,
    SUBTITLE_STYLE_PRESETS,
    SubtitleStyle,
    SubtitleStyleHistory,
    apply_subtitle_style_preset,
    resolve_font_size_px,
    resolve_subtitle_style_preset,
    subtitle_style_preset_ids,
    to_preview_style,
    to_renderer_style,
)

_OUTPUT_HEIGHTS = (1920, 1080, 960)


# ------------------------- registry validity -------------------------


def test_every_preset_is_a_valid_in_band_subtitle_style() -> None:
    assert SUBTITLE_STYLE_PRESETS
    for style in SUBTITLE_STYLE_PRESETS.values():
        assert isinstance(style, SubtitleStyle)
        assert MIN_FONT_SIZE_RATIO - 1e-9 <= style.font_size_ratio <= MAX_FONT_SIZE_RATIO + 1e-9


def test_default_preset_matches_the_current_default_ratio() -> None:
    assert SUBTITLE_STYLE_PRESETS["caption_default"].font_size_ratio == pytest.approx(
        DEFAULT_FONT_SIZE_RATIO
    )
    assert DEFAULT_FONT_SIZE_RATIO == pytest.approx(FONT_SIZE_TIERS["medium"])


def test_presets_span_the_named_tier_sizes() -> None:
    assert SUBTITLE_STYLE_PRESETS["caption_small"].font_size_ratio == pytest.approx(
        FONT_SIZE_TIERS["small"]
    )
    assert SUBTITLE_STYLE_PRESETS["caption_large"].font_size_ratio == pytest.approx(
        FONT_SIZE_TIERS["large"]
    )
    assert SUBTITLE_STYLE_PRESETS["caption_xlarge"].font_size_ratio == pytest.approx(
        FONT_SIZE_TIERS["xlarge"]
    )


# ------------------------- preset ids + resolution -------------------------


def test_preset_ids_are_a_sorted_immutable_tuple() -> None:
    ids = subtitle_style_preset_ids()
    assert isinstance(ids, tuple)
    assert list(ids) == sorted(SUBTITLE_STYLE_PRESETS)


def test_resolve_returns_the_registered_style() -> None:
    style = resolve_subtitle_style_preset("caption_large")
    assert style == SUBTITLE_STYLE_PRESETS["caption_large"]
    assert isinstance(style, SubtitleStyle)


def test_resolve_rejects_an_unknown_preset_id() -> None:
    with pytest.raises(ValidationError, match="preset"):
        resolve_subtitle_style_preset("caption_gigantic")


@pytest.mark.parametrize("bad", [None, 123, True])
def test_resolve_rejects_a_non_string_preset_id(bad: object) -> None:
    with pytest.raises(ValidationError, match="preset"):
        resolve_subtitle_style_preset(bad)  # type: ignore[arg-type]


# ------------------------- preset selection undo/redo -------------------------


def test_selecting_a_preset_is_an_undoable_step() -> None:
    history = SubtitleStyleHistory(present=SubtitleStyle())
    applied = apply_subtitle_style_preset(history, "caption_large")
    assert applied.present.font_size_ratio == pytest.approx(FONT_SIZE_TIERS["large"])
    assert applied.past == (SubtitleStyle(),)

    reverted = applied.undo()
    assert reverted.present == SubtitleStyle()


def test_selecting_a_preset_after_undo_clears_the_redo_branch() -> None:
    history = SubtitleStyleHistory(present=SubtitleStyle())
    applied = apply_subtitle_style_preset(history, "caption_large")
    diverged = apply_subtitle_style_preset(applied.undo(), "caption_small")
    assert diverged.future == ()
    assert diverged.present.font_size_ratio == pytest.approx(FONT_SIZE_TIERS["small"])


def test_apply_preset_rejects_an_unknown_id() -> None:
    history = SubtitleStyleHistory(present=SubtitleStyle())
    with pytest.raises(ValidationError, match="preset"):
        apply_subtitle_style_preset(history, "caption_gigantic")


# ------------------------- preview/renderer parity + output-relative -------------------------


@pytest.mark.parametrize("preset_id", ["caption_small", "caption_default", "caption_large", "caption_xlarge"])
@pytest.mark.parametrize("output_height", _OUTPUT_HEIGHTS)
def test_preview_and_renderer_resolve_a_preset_to_the_same_pixels(
    preset_id: str, output_height: int
) -> None:
    style = resolve_subtitle_style_preset(preset_id)
    renderer = to_renderer_style(style, output_height=output_height)["subtitle_font_size"]
    preview = to_preview_style(style, output_height=output_height)["font_size_px"]
    assert renderer == preview
    assert renderer == resolve_font_size_px(style, output_height=output_height)


def test_a_preset_is_output_relative_across_ratios() -> None:
    # The same preset resolves to a proportionally different pixel size at a taller
    # vs shorter output, so captions stay proportionally sized across ratios.
    style = resolve_subtitle_style_preset("caption_default")
    tall = resolve_font_size_px(style, output_height=1920)
    short = resolve_font_size_px(style, output_height=960)
    assert tall == 48
    assert short == 24


# ------------------------- CJK renderer characterization (no ASS duplication) -------------------------


def test_renderer_uses_a_cjk_font_and_threads_the_preset_font_size(tmp_path) -> None:
    # Characterize (not re-implement) the existing renderer: the ASS default style
    # uses the CJK-capable NanumGothic font and the preset-derived font size reaches
    # the generated Fontsize, so a preset renders legible CJK captions.
    srt = tmp_path / "cjk.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:03,000\n안녕하세요 세계\n", encoding="utf-8"
    )
    ass_path = tmp_path / "cjk.ass"
    style = resolve_subtitle_style_preset("caption_large")
    font_size = resolve_font_size_px(style, output_height=1920)

    result = FFmpegService().convert_srt_to_ass(str(srt), str(ass_path), font_size=font_size)
    content = result.read_text(encoding="utf-8")

    default_style_line = next(
        line for line in content.splitlines() if line.startswith("Style: Default,")
    )
    # Positional parse so the font_size assertion cannot false-match another numeric
    # ASS column (scale/margins/border) that happens to equal the size.
    fields = default_style_line.removeprefix("Style: ").split(",")
    assert fields[0] == "Default"
    assert fields[1] == "NanumGothic"
    assert fields[2] == str(font_size)
    assert "안녕하세요 세계" in content
