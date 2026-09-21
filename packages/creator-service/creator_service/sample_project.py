"""SF-75: reproducible, license-clean sample project (synthetic, secret-free).

A pure, deterministic builder for a small demonstration project that exercises
both uploaded and generated media plus editable scenes. It composes only
creator-domain value objects and a service-layer in-memory asset resolver, so it
loads through the supported project contracts and compiles to a RenderPlan for
both Preview and render without touching env, network, disk, or a real model.

Storage keys are workspace-relative synthetic paths (the compiler's contract is
the key string; byte resolution happens later in the storage/render layer), and
every asset carries explicit license + provenance metadata with no secrets and
no private media.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from creator_domain.models import (
    MediaAsset,
    MediaOrigin,
    MediaSegment,
    MediaType,
    Project,
    Timeline,
)

SAMPLE_WORKSPACE_ID = 1
SAMPLE_PROJECT_ID = 1
# Fixed timestamp keeps every builder output byte-identical across calls/machines.
SAMPLE_CREATED_AT = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_GENERATED_ASSET_ID = 10
_UPLOADED_ASSET_ID = 11
_LICENSE = "CC0-1.0"


def build_sample_project(
    *,
    workspace_id: int = SAMPLE_WORKSPACE_ID,
    project_id: int = SAMPLE_PROJECT_ID,
    created_at: datetime = SAMPLE_CREATED_AT,
) -> Project:
    return Project(
        id=project_id,
        workspace_id=workspace_id,
        title="Sample Short Project",
        source_type="idea",
        idea_brief="A synthetic sample demonstrating mixed media and editable scenes.",
        status="active",
        created_at=created_at,
        updated_at=created_at,
    )


def build_sample_media_assets(
    *,
    workspace_id: int = SAMPLE_WORKSPACE_ID,
    project_id: int = SAMPLE_PROJECT_ID,
    created_at: datetime = SAMPLE_CREATED_AT,
) -> tuple[MediaAsset, ...]:
    prefix = f"workspaces/{workspace_id}/assets/sample"
    generated = MediaAsset(
        id=_GENERATED_ASSET_ID,
        workspace_id=workspace_id,
        project_id=project_id,
        media_type=MediaType.IMAGE,
        origin=MediaOrigin.GENERATED,
        storage_key=f"{prefix}/generated-scene-1.png",
        mime_type="image/png",
        width=1080,
        height=1920,
        metadata={
            "license": _LICENSE,
            "provenance": "synthetic",
            "generator": "synthetic-fixture",
            "prompt_snapshot": "a calm synthetic gradient backdrop",
            "note": "no real model call — deterministic fixture",
        },
        created_at=created_at,
    )
    uploaded = MediaAsset(
        id=_UPLOADED_ASSET_ID,
        workspace_id=workspace_id,
        project_id=project_id,
        media_type=MediaType.VIDEO,
        origin=MediaOrigin.UPLOADED,
        storage_key=f"{prefix}/uploaded-clip.mp4",
        mime_type="video/mp4",
        width=1080,
        height=1920,
        duration_seconds=8.0,
        metadata={
            "license": _LICENSE,
            "provenance": "synthetic-upload",
            "note": "bundled synthetic sample — not private media",
        },
        created_at=created_at,
    )
    return (generated, uploaded)


def build_sample_timeline(
    *,
    project_id: int = SAMPLE_PROJECT_ID,
    revision: int = 0,
) -> Timeline:
    segments = [
        MediaSegment(
            id="seg-1",
            scene_id="scene-1",
            asset_id=_GENERATED_ASSET_ID,
            timeline_start_seconds=0.0,
            duration_seconds=4.0,
            fit_mode="cover",
            transition="fade",
        ),
        MediaSegment(
            id="seg-2",
            scene_id="scene-2",
            asset_id=_UPLOADED_ASSET_ID,
            timeline_start_seconds=4.0,
            duration_seconds=4.0,
            trim_start_seconds=0.0,
            trim_end_seconds=4.0,
            fit_mode="cover",
            transition="cut",
        ),
    ]
    return Timeline(
        id="sample-timeline",
        project_id=project_id,
        revision=revision,
        segments=segments,
    )


class SampleAssetResolver:
    """In-memory workspace-scoped AssetResolver over the sample assets."""

    def __init__(self, assets: Sequence[MediaAsset]) -> None:
        self._by_id = {asset.id: asset for asset in assets}

    async def get_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None:
        asset = self._by_id.get(asset_id)
        if asset is None or asset.workspace_id != workspace_id:
            return None
        return asset


def build_sample_asset_resolver(
    *,
    workspace_id: int = SAMPLE_WORKSPACE_ID,
    project_id: int = SAMPLE_PROJECT_ID,
) -> SampleAssetResolver:
    return SampleAssetResolver(
        build_sample_media_assets(workspace_id=workspace_id, project_id=project_id)
    )


@dataclass(frozen=True)
class SampleProjectBundle:
    project: Project
    assets: tuple[MediaAsset, ...]
    timeline: Timeline
    resolver: SampleAssetResolver


def build_sample_project_bundle(
    *,
    workspace_id: int = SAMPLE_WORKSPACE_ID,
    project_id: int = SAMPLE_PROJECT_ID,
    created_at: datetime = SAMPLE_CREATED_AT,
) -> SampleProjectBundle:
    assets = build_sample_media_assets(
        workspace_id=workspace_id, project_id=project_id, created_at=created_at
    )
    return SampleProjectBundle(
        project=build_sample_project(
            workspace_id=workspace_id, project_id=project_id, created_at=created_at
        ),
        assets=assets,
        timeline=build_sample_timeline(project_id=project_id),
        resolver=SampleAssetResolver(assets),
    )
