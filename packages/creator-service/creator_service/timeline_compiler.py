"""SF-29: compile a saved Timeline revision into a resolved RenderPlan.

Each MediaSegment is resolved deterministically: its asset_id is looked up in a
workspace-scoped asset resolver, ownership is validated (asset must belong to the
timeline's project + the caller's workspace), the media_type is mapped to a
RenderSegmentKind, storage_key becomes the render source, and video trims are
validated against the source duration. Only supported transitions are allowed.
The compile is a pure function of the timeline + assets, so re-compiling the same
inputs yields an identical RenderPlan (no stale pipeline state).
"""

from __future__ import annotations

from typing import Protocol

from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    EncodingProfile,
    MediaAsset,
    MediaSegment,
    MediaType,
    OutputSpec,
    RenderPlan,
    RenderSegment,
    RenderSegmentKind,
    Timeline,
)

_SUPPORTED_TRANSITIONS = frozenset({"cut", "fade", "ken_burns", "ken_burns_lite"})

_MEDIA_KIND: dict[MediaType, RenderSegmentKind] = {
    MediaType.IMAGE: RenderSegmentKind.IMAGE,
    MediaType.LOGO: RenderSegmentKind.IMAGE,
    MediaType.GRAPHIC: RenderSegmentKind.IMAGE,
    MediaType.VIDEO: RenderSegmentKind.VIDEO,
}


class AssetResolver(Protocol):
    """Workspace-scoped media asset lookup used during compilation."""

    async def get_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None: ...


async def compile_timeline_to_render_plan(
    timeline: Timeline,
    *,
    workspace_id: int,
    output_spec: OutputSpec,
    encoding_profile: EncodingProfile,
    asset_resolver: AssetResolver,
) -> RenderPlan:
    if not timeline.segments:
        raise ValidationError("Timeline has no segments to compile")

    render_segments: list[RenderSegment] = []
    for segment in sorted(timeline.segments, key=lambda s: s.timeline_start_seconds):
        asset = await asset_resolver.get_asset(segment.asset_id, workspace_id)
        if (
            asset is None
            or asset.workspace_id != workspace_id
            or asset.project_id != timeline.project_id
        ):
            raise ValidationError(
                f"Timeline segment {segment.id!r} references an unavailable asset"
            )
        if not asset.storage_key:
            raise ValidationError(
                f"Asset {asset.id} has no storage source to render"
            )

        kind = _MEDIA_KIND.get(asset.media_type)
        if kind is None:
            raise ValidationError(
                f"Asset {asset.id} media type {asset.media_type.value!r} is not renderable"
            )

        if segment.transition is not None and segment.transition not in _SUPPORTED_TRANSITIONS:
            raise ValidationError(
                f"Unsupported transition {segment.transition!r}"
            )

        _validate_source_bounds(segment=segment, asset=asset, kind=kind)

        render_segments.append(
            RenderSegment(
                kind=kind,
                source=asset.storage_key,
                timeline_start_seconds=segment.timeline_start_seconds,
                duration_seconds=segment.duration_seconds,
                trim_start_seconds=segment.trim_start_seconds,
                trim_end_seconds=segment.trim_end_seconds,
                fit_mode=segment.fit_mode,
                transition=segment.transition,
            )
        )

    return RenderPlan(
        segments=render_segments,
        output_spec=output_spec,
        encoding_profile=encoding_profile,
    )


def _validate_source_bounds(
    *, segment: MediaSegment, asset: MediaAsset, kind: RenderSegmentKind
) -> None:
    """Reject video trims that exceed the source's known duration.

    Images have no intrinsic duration, so only video sources are bounds-checked,
    and only when the source duration is known. The effective source end is
    ``trim_end`` when set, otherwise ``trim_start + duration_seconds`` — matching
    the renderer's implicit-range semantics, so an omitted trim_end cannot smuggle
    an overrun past compilation.
    """
    if kind is not RenderSegmentKind.VIDEO or asset.duration_seconds is None:
        return
    trim_start = segment.trim_start_seconds or 0.0
    effective_end = (
        segment.trim_end_seconds
        if segment.trim_end_seconds is not None
        else trim_start + segment.duration_seconds
    )
    if effective_end > asset.duration_seconds + 1e-6:
        raise ValidationError(
            f"Asset {asset.id} source range end {effective_end} exceeds source "
            f"duration {asset.duration_seconds}"
        )
