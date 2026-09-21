"""SF-58: deterministic AI shorten command builder.

build_shorten_proposal turns "make this draft ~N seconds" into a valid
CommandProposal (SF-55) using ONLY existing timing/deletion commands, so it flows
unchanged through SF-56 apply and SF-57 diff. The strategy is a prefix-preserving
tail cut: the opening segments stay intact, every segment after the target cut
point is ripple-deleted (keeping the timeline contiguous — no gaps, so narration/
caption timing stays coherent), and the boundary segment's tail is trimmed so the
retained content lands on the target within tolerance. Trims only shrink a
segment's window relative to its existing trim_start, so source bounds are always
preserved.

The applier has no rippling trim (a bare trim on a middle segment leaves a gap and
may not reduce total duration), so tail-delete + trailing-trim is the only
coherent way to actually shorten with the current command set. Unsupported
requests raise a typed ValidationError with a distinct message: a non-positive
target, a negative tolerance, a timeline already within target, or a target so
small it cannot be reached without dropping the opening content.
"""

from __future__ import annotations

import math

from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    DeleteSegmentCommand,
    EditorCommand,
    MediaSegment,
    TrimSegmentCommand,
)

from creator_service.command_proposal import CommandProposal
from creator_service.editor_history import EditorHistory

# Technical floor for a trimmed boundary segment: the domain requires a strictly
# positive duration, so a target landing within this epsilon of a segment's start
# cannot yield a valid trim and is treated as unreachable.
_MIN_SEGMENT_SECONDS = 1e-3


async def build_shorten_proposal(
    history: EditorHistory,
    *,
    target_seconds: float,
    tolerance_seconds: float,
) -> CommandProposal:
    """Build a prefix-preserving tail-cut proposal to reach ~target_seconds."""
    if not math.isfinite(target_seconds):
        raise ValidationError("shorten target must be a finite duration")
    if not math.isfinite(tolerance_seconds):
        raise ValidationError("shorten tolerance must be a finite number")
    if target_seconds <= 0:
        raise ValidationError("shorten target must be a positive duration")
    if tolerance_seconds < 0:
        raise ValidationError("shorten tolerance must not be negative")

    before, generation = await history.capture()
    current_total = before.total_duration_seconds
    if current_total <= target_seconds + tolerance_seconds:
        raise ValidationError(
            "timeline is already within the target duration; nothing to shorten"
        )

    ordered = sorted(before.segments, key=lambda s: s.timeline_start_seconds)
    boundary_index = _find_boundary_index(ordered, target_seconds)
    if boundary_index is None:
        return _shorten_at_gap(
            ordered, target_seconds=target_seconds, tolerance_seconds=tolerance_seconds,
            generation=generation,
        )

    boundary = ordered[boundary_index]
    later = ordered[boundary_index + 1 :]

    commands: list[EditorCommand] = [
        DeleteSegmentCommand(segment_id=s.id, policy="ripple") for s in reversed(later)
    ]

    kept_duration = target_seconds - boundary.timeline_start_seconds
    if _needs_trim(boundary, kept_duration):
        if kept_duration <= _MIN_SEGMENT_SECONDS:
            raise ValidationError(
                "cannot reach the target duration without dropping the opening content"
            )
        trim_start = boundary.trim_start_seconds or 0.0
        commands.append(
            TrimSegmentCommand(
                segment_id=boundary.id,
                trim_start_seconds=trim_start,
                trim_end_seconds=trim_start + kept_duration,
            )
        )

    if not commands:
        raise ValidationError(
            "cannot reach the target duration without dropping the opening content"
        )

    return CommandProposal(base_revision=generation, commands=commands)


def _shorten_at_gap(
    ordered: list[MediaSegment],
    *,
    target_seconds: float,
    tolerance_seconds: float,
    generation: int,
) -> CommandProposal:
    # The target fell before the first segment start or in a gap, so no segment
    # can be trimmed to land on it. The best a delete-only cut can reach is the end
    # of the last segment that ends before the target; accept it only when that
    # undershoot is within tolerance, otherwise the target is unreachable.
    prefix = [s for s in ordered if s.timeline_start_seconds + s.duration_seconds < target_seconds]
    if not prefix:
        raise ValidationError(
            "cannot reach the target duration without dropping the opening content"
        )
    closest_end = max(s.timeline_start_seconds + s.duration_seconds for s in prefix)
    if target_seconds - closest_end > tolerance_seconds + 1e-9:
        raise ValidationError(
            "cannot reach the target duration with the available cut points"
        )
    kept_ids = {s.id for s in prefix}
    later = [s for s in ordered if s.id not in kept_ids]
    commands: list[EditorCommand] = [
        DeleteSegmentCommand(segment_id=s.id, policy="ripple") for s in reversed(later)
    ]
    return CommandProposal(base_revision=generation, commands=commands)


def _find_boundary_index(ordered: list[MediaSegment], target_seconds: float) -> int | None:
    # The boundary segment is the one whose half-open span [start, start+duration)
    # contains the target, or that ends exactly at the target. Everything after it
    # is dropped; it is trimmed (unless the target is exactly its end). A target in
    # a gap or before the first segment's end has no boundary and is handled by
    # _shorten_at_gap.
    for index, segment in enumerate(ordered):
        start = segment.timeline_start_seconds
        end = start + segment.duration_seconds
        if start < target_seconds <= end + 1e-9:
            return index
    return None


def _needs_trim(boundary: MediaSegment, kept_duration: float) -> bool:
    return kept_duration + 1e-9 < boundary.duration_seconds
