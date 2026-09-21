"""SF-59: deterministic AI pacing command builder.

build_pacing_proposal turns "make the opening faster/slower" into a valid
CommandProposal (SF-55) using ONLY existing duration/transition commands, so it
flows unchanged through SF-56 apply and SF-57 diff. Pacing scales in-scope segment
durations by a factor via resizeSegment (whose ripple keeps the timeline
contiguous so nothing desyncs), optionally pairing a transition kind. Video
segments are clamped to their remaining source duration so source bounds are
respected; a slower video already at its source max is skipped rather than
emitting a no-op resize. Scope is by scene id: unrelated scenes keep their content
(asset/duration/trim/transition), shifting only in placement from the ripple — the
intended pacing behavior, not a content mutation.

Unsupported requests raise a typed ValidationError: a near-1.0 or non-positive or
non-finite factor, an unknown scene id (never silently ignored, mirroring the
hallucinated-id strictness of the apply boundary), or a scope that yields no
actual change (every scoped segment already at its source max and no transition
change), since a CommandProposal needs at least one command.
"""

from __future__ import annotations

import math

from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    EditorCommand,
    MediaSegment,
    ResizeSegmentCommand,
    SetTransitionCommand,
)
from pydantic import ValidationError as PydanticValidationError

from creator_service.command_proposal import CommandProposal
from creator_service.editor_command_applier import EditorAssetLookup
from creator_service.editor_history import EditorHistory

# Relative tolerance for treating a pacing factor as an effective no-op: a factor
# within this of 1.0 changes no duration meaningfully and is rejected.
_FACTOR_EPSILON = 1e-6
_IMAGE_KINDS = frozenset({"IMAGE", "LOGO", "GRAPHIC"})


async def build_pacing_proposal(
    history: EditorHistory,
    *,
    factor: float,
    scene_ids: list[str] | None = None,
    transition: str | None = None,
) -> CommandProposal:
    """Build a scoped resize (+ optional transition) proposal to re-pace segments."""
    if not math.isfinite(factor):
        raise ValidationError("pacing factor must be a finite number")
    if factor <= 0:
        raise ValidationError("pacing factor must be a positive multiplier")
    if abs(factor - 1.0) <= _FACTOR_EPSILON:
        raise ValidationError("pacing factor must differ from 1.0 to change pacing")

    before, generation = await history.capture()
    ordered = sorted(before.segments, key=lambda s: s.timeline_start_seconds)
    in_scope = _select_scope(ordered, scene_ids)

    commands: list[EditorCommand] = []
    for segment in in_scope:
        resized = await _paced_duration(segment, factor, history.workspace_id, history.asset_lookup)
        if resized is not None:
            commands.append(
                ResizeSegmentCommand(segment_id=segment.id, duration_seconds=resized)
            )
        if transition is not None and segment.transition != transition:
            commands.append(_transition_command(segment.id, transition))

    if not commands:
        raise ValidationError("no pacing change available for the requested scope")

    return CommandProposal(base_revision=generation, commands=commands)


def _select_scope(
    ordered: list[MediaSegment], scene_ids: list[str] | None
) -> list[MediaSegment]:
    if scene_ids is None:
        return ordered
    requested = set(scene_ids)
    present = {s.scene_id for s in ordered}
    unknown = requested - present
    if unknown:
        raise ValidationError(f"unknown scene ids: {sorted(unknown)}")
    in_scope = [s for s in ordered if s.scene_id in requested]
    if not in_scope:
        raise ValidationError("no segments match the requested scene scope")
    return in_scope


async def _paced_duration(
    segment: MediaSegment, factor: float, workspace_id: int, lookup: EditorAssetLookup
) -> float | None:
    # New duration = current * factor, clamped to the remaining source window for
    # video (images are unbounded). Returns None when the clamped result does not
    # meaningfully differ from the current duration (a per-segment no-op to skip).
    requested = segment.duration_seconds * factor
    asset = await lookup.get_asset_for_editor(segment.asset_id, workspace_id)
    if asset is None:
        raise ValidationError(f"segment {segment.id!r} references an unavailable asset")
    if asset.media_type not in _IMAGE_KINDS:
        available = asset.duration_seconds - (segment.trim_start_seconds or 0.0)
        requested = min(requested, available)
    if requested <= 0 or abs(requested - segment.duration_seconds) <= _FACTOR_EPSILON:
        return None
    return requested


def _transition_command(segment_id: str, transition: str) -> SetTransitionCommand:
    try:
        return SetTransitionCommand.model_validate(
            {"segment_id": segment_id, "transition": transition}
        )
    except PydanticValidationError as error:
        raise ValidationError(f"unsupported transition: {transition!r}") from error
