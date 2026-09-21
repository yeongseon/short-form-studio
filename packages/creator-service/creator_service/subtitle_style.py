"""SF-61: deterministic AI subtitle-style command translator and validator.

Subtitle style is a RENDER-TIME concern (RenderProfile.subtitle_font_size fed to
ffmpeg force_style), NOT a Timeline edit — there is no subtitleStyle EditorCommand
and the Timeline applier rejects style commands. So this module is a self-contained
subtitle-style domain, intentionally separate from EditorCommand / CommandProposal
/ ProposalDiff / EditorHistory, and is never routed through apply_editor_command.

The canonical state is a font-size RATIO of the output height, so a style is
output-relative by construction and renders correctly across presets. Requests
like "larger captions" translate through named tiers into a ratio; explicit ratios
are clamped-band validated; relative requests clamp to the band (a no-op at the
boundary) rather than throwing. A dedicated StyleDiff and a tiny pure
SubtitleStyleHistory give real style-only diffs and Apply/Undo parity without
touching the Timeline. Malformed values raise a typed ValidationError.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal

from creator_domain.exceptions import ValidationError

# Default derived from the current render behavior: RenderProfile.subtitle_font_size
# is 48px at a 1920px-tall output, so the default ratio resolves back to 48 there.
_DEFAULT_OUTPUT_HEIGHT = 1920
_DEFAULT_SUBTITLE_FONT_SIZE_PX = 48
DEFAULT_FONT_SIZE_RATIO = _DEFAULT_SUBTITLE_FONT_SIZE_PX / _DEFAULT_OUTPUT_HEIGHT

# Validation band (output-relative), wider than the named tiers so explicit ratios
# have headroom while staying legible and non-degenerate.
MIN_FONT_SIZE_RATIO = 30 / _DEFAULT_OUTPUT_HEIGHT
MAX_FONT_SIZE_RATIO = 120 / _DEFAULT_OUTPUT_HEIGHT

# Named tiers are product-decision translation sugar; canonical storage is the ratio.
FONT_SIZE_TIERS: dict[str, float] = {
    "small": 42 / _DEFAULT_OUTPUT_HEIGHT,
    "medium": 48 / _DEFAULT_OUTPUT_HEIGHT,
    "large": 64 / _DEFAULT_OUTPUT_HEIGHT,
    "xlarge": 80 / _DEFAULT_OUTPUT_HEIGHT,
}
_TIER_ORDER = ("small", "medium", "large", "xlarge")


def _validate_ratio(ratio: object) -> float:
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
        raise ValidationError("subtitle font_size_ratio must be a number")
    value = float(ratio)
    if not math.isfinite(value):
        raise ValidationError("subtitle font_size_ratio must be finite")
    if value <= 0:
        raise ValidationError("subtitle font_size_ratio must be positive")
    if value < MIN_FONT_SIZE_RATIO - 1e-9 or value > MAX_FONT_SIZE_RATIO + 1e-9:
        raise ValidationError(
            f"subtitle font_size_ratio must be within "
            f"[{MIN_FONT_SIZE_RATIO}, {MAX_FONT_SIZE_RATIO}]"
        )
    return value


@dataclass(frozen=True)
class SubtitleStyle:
    font_size_ratio: float = DEFAULT_FONT_SIZE_RATIO

    def __post_init__(self) -> None:
        # The canonical model enforces its own invariant so an invalid style can
        # never exist to leak into the renderer/preview helpers.
        _validate_ratio(self.font_size_ratio)


@dataclass(frozen=True)
class SubtitleStyleCommand:
    font_size_ratio: float
    type: Literal["subtitleStyle"] = "subtitleStyle"

    def __post_init__(self) -> None:
        _validate_ratio(self.font_size_ratio)


@dataclass(frozen=True)
class StyleDiff:
    before: SubtitleStyle
    after: SubtitleStyle
    changed_fields: tuple[Literal["font_size_ratio"], ...]


def resolve_font_size_px(style: SubtitleStyle, *, output_height: int) -> int:
    """Resolve the output-relative ratio to an absolute pixel size (round half up)."""
    if not isinstance(output_height, int) or isinstance(output_height, bool) or output_height <= 0:
        raise ValidationError("output height must be a positive whole number of pixels")
    return max(1, int(math.floor(style.font_size_ratio * output_height + 0.5)))


def to_renderer_style(style: SubtitleStyle, *, output_height: int) -> dict[str, int]:
    return {"subtitle_font_size": resolve_font_size_px(style, output_height=output_height)}


def to_preview_style(style: SubtitleStyle, *, output_height: int) -> dict[str, int]:
    return {"font_size_px": resolve_font_size_px(style, output_height=output_height)}


def _clamp_ratio(ratio: float) -> float:
    return min(MAX_FONT_SIZE_RATIO, max(MIN_FONT_SIZE_RATIO, ratio))


def _nearest_tier_index(ratio: float) -> int:
    return min(
        range(len(_TIER_ORDER)),
        key=lambda i: abs(FONT_SIZE_TIERS[_TIER_ORDER[i]] - ratio),
    )


def translate_subtitle_style_request(
    current: SubtitleStyle, request: dict[str, object]
) -> SubtitleStyle:
    """Translate one style request (tier | relative | font_size_ratio) into a style.

    Exactly one supported key is required. A named tier maps to its ratio, a
    relative verb moves one tier from the current size and clamps to the band, and
    an explicit ratio is band-validated. Unknown keys/verbs/tiers and empty or
    multi-key requests raise ValidationError.
    """
    if not isinstance(request, dict):
        raise ValidationError("subtitle style request must be an object")
    if not request:
        raise ValidationError("subtitle style request must not be empty")
    supported = {"tier", "relative", "font_size_ratio"}
    keys = set(request.keys())
    unsupported = keys - supported
    if unsupported:
        raise ValidationError(f"unsupported subtitle style fields: {sorted(unsupported)}")
    if len(keys) != 1:
        raise ValidationError("subtitle style request must have exactly one directive")

    if "tier" in request:
        tier = request["tier"]
        if not isinstance(tier, str) or tier not in FONT_SIZE_TIERS:
            raise ValidationError(f"unknown subtitle size tier: {tier!r}")
        return SubtitleStyle(font_size_ratio=FONT_SIZE_TIERS[tier])

    if "relative" in request:
        verb = request["relative"]
        if verb not in ("larger", "smaller"):
            raise ValidationError(f"unknown relative subtitle size verb: {verb!r}")
        step = 1 if verb == "larger" else -1
        index = _nearest_tier_index(current.font_size_ratio)
        next_index = min(len(_TIER_ORDER) - 1, max(0, index + step))
        target = FONT_SIZE_TIERS[_TIER_ORDER[next_index]]
        return SubtitleStyle(font_size_ratio=_clamp_ratio(max(target, current.font_size_ratio) if step > 0 else min(target, current.font_size_ratio)))

    ratio = request["font_size_ratio"]
    if not isinstance(ratio, (int, float)) or isinstance(ratio, bool):
        raise ValidationError("font_size_ratio must be a number")
    return SubtitleStyle(font_size_ratio=_validate_ratio(float(ratio)))


def diff_subtitle_style(before: SubtitleStyle, after: SubtitleStyle) -> StyleDiff:
    changed: tuple[Literal["font_size_ratio"], ...] = (
        ("font_size_ratio",) if before.font_size_ratio != after.font_size_ratio else ()
    )
    return StyleDiff(before=before, after=after, changed_fields=changed)


@dataclass(frozen=True)
class SubtitleStyleHistory:
    present: SubtitleStyle
    past: tuple[SubtitleStyle, ...] = field(default_factory=tuple)
    future: tuple[SubtitleStyle, ...] = field(default_factory=tuple)

    def undo(self) -> SubtitleStyleHistory:
        if not self.past:
            return self
        return SubtitleStyleHistory(
            present=self.past[-1],
            past=self.past[:-1],
            future=(self.present, *self.future),
        )

    def redo(self) -> SubtitleStyleHistory:
        if not self.future:
            return self
        return SubtitleStyleHistory(
            present=self.future[0],
            past=(*self.past, self.present),
            future=self.future[1:],
        )


def apply_subtitle_style(
    history: SubtitleStyleHistory, command: SubtitleStyleCommand
) -> SubtitleStyleHistory:
    """Apply a validated style command as one undoable step, clearing the redo branch."""
    new_present = replace(history.present, font_size_ratio=command.font_size_ratio)
    return SubtitleStyleHistory(
        present=new_present,
        past=(*history.past, history.present),
        future=(),
    )
