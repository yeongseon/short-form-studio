"""SF-48: applier for the shared validated EditorCommand boundary.

apply_editor_command validates the claimed base revision, command references,
workspace-scoped asset access, and source bounds, then rebuilds a NEW Timeline
atomically — the input Timeline and its segments are never mutated, so a
validation failure at any step leaves the original untouched (no partial
mutation). Persistence and optimistic-concurrency stay in TimelineService.save;
this applier only checks base_revision as defense-in-depth against applying a
stale intent, and returns the edited Timeline with its revision unchanged (the
save layer bumps it).

Output/style/audio commands are part of the typed contract but the current
Timeline model has no such fields, so they are explicitly rejected here rather
than silently no-oped.
"""

from __future__ import annotations

from typing import ClassVar, Protocol

from creator_domain.exceptions import ValidationError, VersionConflictError
from creator_domain.models import (
    DeleteSegmentCommand,
    MediaSegment,
    MoveSegmentCommand,
    ReplaceAssetCommand,
    ResizeSegmentCommand,
    SetTransitionCommand,
    SplitSegmentCommand,
    Timeline,
    TrimSegmentCommand,
)
from pydantic import BaseModel, ConfigDict, Field

_IMAGE_KINDS = frozenset({"IMAGE", "LOGO", "GRAPHIC"})


class EditorAssetRef(BaseModel):
    """The asset facts the applier needs to validate a command.

    Resolved via a workspace-scoped lookup, so a ``None`` result already means
    missing or cross-workspace; ``project_id`` and ``media_type`` drive
    cross-project and kind-compatibility checks, and ``duration_seconds`` drives
    source-bound checks.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    project_id: int = Field(ge=1)
    media_type: str = Field(min_length=1)
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)


class EditorAssetLookup(Protocol):
    """Workspace-scoped asset resolver used for command validation."""

    async def get_asset_for_editor(
        self, asset_id: int, workspace_id: int
    ) -> EditorAssetRef | None: ...


def _broad_kind(media_type: str) -> str:
    return "image" if media_type in _IMAGE_KINDS else media_type.lower()


def _find(segments: list[MediaSegment], segment_id: str) -> MediaSegment:
    for segment in segments:
        if segment.id == segment_id:
            return segment
    raise ValidationError(f"segment not found: {segment_id}")


def _resequence(segments: list[MediaSegment]) -> list[MediaSegment]:
    cursor = 0.0
    placed: list[MediaSegment] = []
    for segment in segments:
        placed.append(segment.model_copy(update={"timeline_start_seconds": cursor}))
        cursor += segment.duration_seconds
    return placed


async def _effective_source_duration(
    segment: MediaSegment, workspace_id: int, lookup: EditorAssetLookup
) -> float | None:
    asset = await lookup.get_asset_for_editor(segment.asset_id, workspace_id)
    if asset is None:
        raise ValidationError(f"segment {segment.id!r} references an unavailable asset")
    if _broad_kind(asset.media_type) == "image":
        return None
    return asset.duration_seconds


async def _apply_trim(
    segments: list[MediaSegment], command: TrimSegmentCommand, workspace_id: int,
    lookup: EditorAssetLookup,
) -> list[MediaSegment]:
    target = _find(segments, command.segment_id)
    if command.trim_start_seconds > command.trim_end_seconds:
        raise ValidationError("trim_start_seconds must be <= trim_end_seconds")
    source = await _effective_source_duration(target, workspace_id, lookup)
    if source is not None and command.trim_end_seconds > source + 1e-6:
        raise ValidationError("trim exceeds source duration")
    window = command.trim_end_seconds - command.trim_start_seconds
    return [
        s.model_copy(
            update={
                "trim_start_seconds": command.trim_start_seconds,
                "trim_end_seconds": command.trim_end_seconds,
                "duration_seconds": window,
            }
        )
        if s.id == command.segment_id
        else s
        for s in segments
    ]


async def _apply_split(
    segments: list[MediaSegment], command: SplitSegmentCommand,
) -> list[MediaSegment]:
    target = _find(segments, command.segment_id)
    start = target.timeline_start_seconds
    end = start + target.duration_seconds
    if command.at_seconds <= start + 1e-9 or command.at_seconds >= end - 1e-9:
        raise ValidationError("split must fall strictly inside the segment")
    left_duration = command.at_seconds - start
    right_duration = end - command.at_seconds
    trim_split = (
        target.trim_start_seconds + left_duration
        if target.trim_start_seconds is not None
        else None
    )
    result: list[MediaSegment] = []
    for segment in segments:
        if segment.id != command.segment_id:
            result.append(segment)
            continue
        result.append(
            segment.model_copy(
                update={
                    "id": f"{segment.id}:a",
                    "duration_seconds": left_duration,
                    "trim_end_seconds": trim_split,
                }
            )
        )
        result.append(
            segment.model_copy(
                update={
                    "id": f"{segment.id}:b",
                    "timeline_start_seconds": command.at_seconds,
                    "duration_seconds": right_duration,
                    "trim_start_seconds": trim_split,
                }
            )
        )
    return result


def _apply_delete(
    segments: list[MediaSegment], command: DeleteSegmentCommand,
) -> list[MediaSegment]:
    target = _find(segments, command.segment_id)
    remaining = [s for s in segments if s.id != command.segment_id]
    if command.policy == "gap":
        return remaining
    return [
        s.model_copy(
            update={"timeline_start_seconds": s.timeline_start_seconds - target.duration_seconds}
        )
        if s.timeline_start_seconds >= target.timeline_start_seconds
        else s
        for s in remaining
    ]


async def _apply_replace(
    segments: list[MediaSegment], command: ReplaceAssetCommand, timeline: Timeline,
    workspace_id: int, lookup: EditorAssetLookup,
) -> list[MediaSegment]:
    target = _find(segments, command.segment_id)
    old = await lookup.get_asset_for_editor(target.asset_id, workspace_id)
    new = await lookup.get_asset_for_editor(command.asset_id, workspace_id)
    if new is None or new.project_id != timeline.project_id:
        raise ValidationError("replacement asset is unavailable")
    if old is not None and _broad_kind(old.media_type) != _broad_kind(new.media_type):
        raise ValidationError("replacement asset media kind is incompatible")

    update: dict[str, object] = {"asset_id": command.asset_id}
    if _broad_kind(new.media_type) != "image":
        trim_start = min(target.trim_start_seconds or 0.0, max(0.0, new.duration_seconds - 1e-3))
        window_end = (
            target.trim_end_seconds
            if target.trim_end_seconds is not None
            else trim_start + target.duration_seconds
        )
        trim_end = min(window_end, new.duration_seconds)
        if (
            trim_end < window_end
            or (target.trim_start_seconds or 0.0) != trim_start
            or target.duration_seconds > trim_end - trim_start
        ):
            update["trim_start_seconds"] = trim_start
            update["trim_end_seconds"] = trim_end
            update["duration_seconds"] = trim_end - trim_start
    return [
        s.model_copy(update=update) if s.id == command.segment_id else s for s in segments
    ]


def _apply_move(
    segments: list[MediaSegment], command: MoveSegmentCommand,
) -> list[MediaSegment]:
    from_index = next(
        (i for i, s in enumerate(segments) if s.id == command.segment_id), -1
    )
    if from_index == -1:
        raise ValidationError(f"segment not found: {command.segment_id}")
    if command.target_index >= len(segments):
        raise ValidationError("target index out of range")
    without = segments[:from_index] + segments[from_index + 1 :]
    reordered = (
        without[: command.target_index]
        + [segments[from_index]]
        + without[command.target_index :]
    )
    return _resequence(reordered)


async def _apply_resize(
    segments: list[MediaSegment], command: ResizeSegmentCommand, workspace_id: int,
    lookup: EditorAssetLookup,
) -> list[MediaSegment]:
    index = next((i for i, s in enumerate(segments) if s.id == command.segment_id), -1)
    if index == -1:
        raise ValidationError(f"segment not found: {command.segment_id}")
    target = segments[index]
    source = await _effective_source_duration(target, workspace_id, lookup)
    resize_update: dict[str, object] = {"duration_seconds": command.duration_seconds}
    if source is not None:
        trim_start = target.trim_start_seconds or 0.0
        available = source - trim_start
        if command.duration_seconds > available + 1e-6:
            raise ValidationError("resize exceeds remaining source duration")
        if target.trim_end_seconds is not None:
            resize_update["trim_end_seconds"] = trim_start + command.duration_seconds
    delta = command.duration_seconds - target.duration_seconds
    return [
        s.model_copy(update=resize_update)
        if i == index
        else (
            s.model_copy(update={"timeline_start_seconds": s.timeline_start_seconds + delta})
            if i > index
            else s
        )
        for i, s in enumerate(segments)
    ]


def _apply_transition(
    segments: list[MediaSegment], command: SetTransitionCommand,
) -> list[MediaSegment]:
    if command.duration_seconds is not None:
        raise ValidationError(
            "transition duration is not yet supported by the Timeline model"
        )
    _find(segments, command.segment_id)
    return [
        s.model_copy(update={"transition": command.transition})
        if s.id == command.segment_id
        else s
        for s in segments
    ]


async def apply_editor_command(
    timeline: Timeline,
    command: object,
    *,
    workspace_id: int,
    base_revision: int,
    asset_lookup: EditorAssetLookup,
) -> Timeline:
    """Validate and apply a command, returning a new Timeline (input untouched)."""
    if base_revision != timeline.revision:
        raise VersionConflictError(timeline.project_id, base_revision, timeline.revision)

    segments = list(timeline.segments)

    if isinstance(command, TrimSegmentCommand):
        new_segments = await _apply_trim(segments, command, workspace_id, asset_lookup)
    elif isinstance(command, SplitSegmentCommand):
        new_segments = await _apply_split(segments, command)
    elif isinstance(command, DeleteSegmentCommand):
        new_segments = _apply_delete(segments, command)
    elif isinstance(command, ReplaceAssetCommand):
        new_segments = await _apply_replace(
            segments, command, timeline, workspace_id, asset_lookup
        )
    elif isinstance(command, MoveSegmentCommand):
        new_segments = _apply_move(segments, command)
    elif isinstance(command, ResizeSegmentCommand):
        new_segments = await _apply_resize(segments, command, workspace_id, asset_lookup)
    elif isinstance(command, SetTransitionCommand):
        new_segments = _apply_transition(segments, command)
    else:
        raise ValidationError(
            f"command type {type(command).__name__} is not applicable to the Timeline"
        )

    return Timeline.model_validate(
        {
            "id": timeline.id,
            "project_id": timeline.project_id,
            "revision": timeline.revision,
            "segments": [s.model_dump(mode="json") for s in new_segments],
        }
    )
