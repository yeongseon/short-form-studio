"""SF-61: deterministic AI subtitle-style command translator and validator.

Subtitle style is a RENDER-TIME concern (RenderProfile.subtitle_font_size fed to
ffmpeg force_style), NOT a Timeline edit — there is no subtitleStyle EditorCommand
and the Timeline applier rejects style commands. So this module is a self-contained
subtitle-style domain, intentionally separate from EditorCommand / CommandProposal
/ ProposalDiff / EditorHistory.

The canonical state is a font-size RATIO of the output height, so a style is
output-relative by construction and renders correctly across presets (1080x1920,
540x960 fast_preview). Requests like "larger captions" translate through named
tiers into a ratio; explicit ratios are clamped-band validated; relative requests
clamp to the band (no-op diff at the boundary) rather than throwing. A dedicated
StyleDiff and a tiny pure SubtitleStyleHistory give real, testable style-only diffs
and Apply/Undo parity without touching the Timeline. Malformed values raise a typed
ValidationError.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_service.subtitle_style import (
    DEFAULT_FONT_SIZE_RATIO,
    MAX_FONT_SIZE_RATIO,
    MIN_FONT_SIZE_RATIO,
    StyleDiff,
    SubtitleStyle,
    SubtitleStyleCommand,
    SubtitleStyleHistory,
    apply_subtitle_style,
    diff_subtitle_style,
    resolve_font_size_px,
    to_preview_style,
    to_renderer_style,
    translate_subtitle_style_request,
)


def test_default_ratio_preserves_current_render_profile_font_size() -> None:
    # RenderProfile default is 48px at 1920 height, so the default ratio must
    # resolve back to exactly 48 at that height (no visual change on default).
    assert DEFAULT_FONT_SIZE_RATIO == pytest.approx(48 / 1920)
    assert resolve_font_size_px(SubtitleStyle(), output_height=1920) == 48


def test_ratio_is_output_relative_across_presets() -> None:
    style = SubtitleStyle()
    assert resolve_font_size_px(style, output_height=1920) == 48
    # fast_preview is 960 tall -> half the pixels for the same relative size
    assert resolve_font_size_px(style, output_height=960) == 24


def test_translate_named_tier_larger_increases_ratio() -> None:
    style = translate_subtitle_style_request(SubtitleStyle(), {"tier": "large"})
    assert style.font_size_ratio > DEFAULT_FONT_SIZE_RATIO
    assert MIN_FONT_SIZE_RATIO <= style.font_size_ratio <= MAX_FONT_SIZE_RATIO


def test_translate_relative_larger_moves_one_tier_up() -> None:
    style = translate_subtitle_style_request(SubtitleStyle(), {"relative": "larger"})
    assert style.font_size_ratio > DEFAULT_FONT_SIZE_RATIO


def test_translate_relative_smaller_moves_one_tier_down() -> None:
    style = translate_subtitle_style_request(SubtitleStyle(), {"relative": "smaller"})
    assert style.font_size_ratio < DEFAULT_FONT_SIZE_RATIO


def test_translate_relative_larger_at_max_clamps_to_band_not_throw() -> None:
    # A relative "larger" request from the top of the band clamps to MAX and
    # yields a no-op diff instead of raising (natural-language intent stays safe).
    maxed = SubtitleStyle(font_size_ratio=MAX_FONT_SIZE_RATIO)
    result = translate_subtitle_style_request(maxed, {"relative": "larger"})
    assert result.font_size_ratio == pytest.approx(MAX_FONT_SIZE_RATIO)


def test_translate_explicit_ratio_within_band_is_accepted() -> None:
    style = translate_subtitle_style_request(SubtitleStyle(), {"font_size_ratio": 0.05})
    assert style.font_size_ratio == pytest.approx(0.05)


def test_resolve_font_size_px_rounds_half_up() -> None:
    style = SubtitleStyle(font_size_ratio=0.05)
    assert resolve_font_size_px(style, output_height=1000) == 50


def test_renderer_and_preview_helpers_expose_px() -> None:
    style = SubtitleStyle()
    assert to_renderer_style(style, output_height=1920) == {"subtitle_font_size": 48}
    assert to_preview_style(style, output_height=1920) == {"font_size_px": 48}


def test_diff_reports_font_size_change() -> None:
    before = SubtitleStyle()
    after = SubtitleStyle(font_size_ratio=0.05)
    diff = diff_subtitle_style(before, after)
    assert isinstance(diff, StyleDiff)
    assert diff.before == before
    assert diff.after == after
    assert diff.changed_fields == ("font_size_ratio",)


def test_diff_of_identical_style_has_no_changed_fields() -> None:
    style = SubtitleStyle()
    diff = diff_subtitle_style(style, style)
    assert diff.changed_fields == ()


def test_apply_moves_present_to_past_and_undo_restores_exactly() -> None:
    history = SubtitleStyleHistory(present=SubtitleStyle())
    command = SubtitleStyleCommand(font_size_ratio=0.05)
    applied = apply_subtitle_style(history, command)
    assert applied.present.font_size_ratio == pytest.approx(0.05)
    assert applied.past == (SubtitleStyle(),)

    reverted = applied.undo()
    assert reverted.present == SubtitleStyle()
    assert reverted.future == (SubtitleStyle(font_size_ratio=0.05),)


def test_redo_reapplies_the_undone_style_exactly() -> None:
    history = SubtitleStyleHistory(present=SubtitleStyle())
    applied = apply_subtitle_style(history, SubtitleStyleCommand(font_size_ratio=0.05))
    redone = applied.undo().redo()
    assert redone.present.font_size_ratio == pytest.approx(0.05)


def test_applying_after_undo_clears_the_redo_branch() -> None:
    history = SubtitleStyleHistory(present=SubtitleStyle())
    applied = apply_subtitle_style(history, SubtitleStyleCommand(font_size_ratio=0.05))
    after_undo = applied.undo()
    diverged = apply_subtitle_style(after_undo, SubtitleStyleCommand(font_size_ratio=0.04))
    assert diverged.future == ()
    assert diverged.present.font_size_ratio == pytest.approx(0.04)


def test_apply_never_touches_timeline_state() -> None:
    # SubtitleStyleHistory is subtitle-style-only; it has no segments/timeline and
    # applying a style command must not require or produce any Timeline object.
    history = SubtitleStyleHistory(present=SubtitleStyle())
    applied = apply_subtitle_style(history, SubtitleStyleCommand(font_size_ratio=0.06))
    assert not hasattr(applied, "segments")
    assert applied.present == SubtitleStyle(font_size_ratio=0.06)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), 0.0, -0.01])
def test_rejects_non_finite_or_non_positive_explicit_ratio(bad: float) -> None:
    with pytest.raises(ValidationError, match="ratio"):
        SubtitleStyleCommand(font_size_ratio=bad)


def test_rejects_ratio_below_or_above_band() -> None:
    with pytest.raises(ValidationError, match="ratio"):
        SubtitleStyleCommand(font_size_ratio=MIN_FONT_SIZE_RATIO / 2)
    with pytest.raises(ValidationError, match="ratio"):
        SubtitleStyleCommand(font_size_ratio=MAX_FONT_SIZE_RATIO * 2)


def test_rejects_non_positive_output_height() -> None:
    with pytest.raises(ValidationError, match="output height"):
        resolve_font_size_px(SubtitleStyle(), output_height=0)


def test_rejects_unknown_tier() -> None:
    with pytest.raises(ValidationError, match="tier"):
        translate_subtitle_style_request(SubtitleStyle(), {"tier": "huge"})


def test_rejects_unknown_relative_verb() -> None:
    with pytest.raises(ValidationError, match="relative"):
        translate_subtitle_style_request(SubtitleStyle(), {"relative": "makeItPop"})


def test_rejects_unsupported_style_field() -> None:
    with pytest.raises(ValidationError, match="unsupported|unknown"):
        translate_subtitle_style_request(SubtitleStyle(), {"color": "#ff0000"})


def test_rejects_empty_request() -> None:
    with pytest.raises(ValidationError, match="no|empty|request"):
        translate_subtitle_style_request(SubtitleStyle(), {})


def test_rejects_ambiguous_request_with_multiple_keys() -> None:
    with pytest.raises(ValidationError, match="one|ambiguous|exactly"):
        translate_subtitle_style_request(
            SubtitleStyle(), {"tier": "large", "relative": "larger"}
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0, -0.01])
def test_rejects_direct_construction_of_invalid_canonical_style(bad: float) -> None:
    # The canonical model enforces its own invariant, so an invalid style can
    # never exist to leak into the renderer/preview helpers.
    with pytest.raises(ValidationError, match="ratio"):
        SubtitleStyle(font_size_ratio=bad)


def test_rejects_boolean_ratio_which_is_not_a_real_size() -> None:
    with pytest.raises(ValidationError, match="ratio"):
        SubtitleStyle(font_size_ratio=True)  # type: ignore[arg-type]


def test_rejects_non_dict_request() -> None:
    with pytest.raises(ValidationError, match="object|request"):
        translate_subtitle_style_request(SubtitleStyle(), ["tier", "large"])  # type: ignore[arg-type]


def test_rejects_non_integer_output_height() -> None:
    with pytest.raises(ValidationError, match="output height"):
        resolve_font_size_px(SubtitleStyle(), output_height=10.5)  # type: ignore[arg-type]

