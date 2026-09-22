"""P0-3: materialize a renderable, sample-backed demo Short.

The demo is only "sample-backed" if the created run has real content behind it.
seed_demo_short creates a NEW workspace-owned project, uploads real placeholder
image bytes for each demo asset (so the timeline is actually renderable, not
metadata-only), persists the asset rows, remaps the sample timeline's segments to
the DB-assigned asset ids, saves the timeline, and — only after all content
persisted — creates the run against that real project. Every persistence call is
scoped to the caller's workspace, so isolation is preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from creator_domain.models import MediaSegment, Timeline
from creator_domain.models.media_type import MediaOrigin, MediaType
from creator_service.demo_short_flow import create_demo_run

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun

# A small solid-color PNG generated locally (no network, no deps) so every seeded
# asset has real bytes at its storage key and the demo timeline is renderable.
_DEMO_IMAGE_WIDTH = 1080
_DEMO_IMAGE_HEIGHT = 1920


@dataclass(frozen=True)
class DemoShortSeedResult:
    run: Any
    project_id: int
    timeline_id: str
    asset_id_map: dict[int, int]


def _placeholder_png(width: int, height: int) -> bytes:
    from creator_provider.image.placeholder_provider import _create_solid_png

    return _create_solid_png(width, height)


async def seed_demo_short(
    *,
    workspace_id: int,
    project_service: Any,
    media_asset_service: Any,
    timeline_service: Any,
    run_service: Any,
) -> DemoShortSeedResult:
    project = await project_service.create_project(
        title="Demo Short",
        source_type="idea",
        idea_brief="A synthetic sample Short you can preview and edit.",
        workspace_id=workspace_id,
    )
    project_id = project.id

    # One renderable image asset backs a single-scene demo timeline. The sample's
    # video asset is intentionally not seeded — there is no local video-byte
    # generator, and Oracle ruled a metadata-only asset is not "sample-backed".
    png = _placeholder_png(_DEMO_IMAGE_WIDTH, _DEMO_IMAGE_HEIGHT)
    storage_key = f"workspaces/{workspace_id}/assets/demo/{project_id}-scene-1.png"
    upload = media_asset_service._backend().upload(storage_key, png, content_type="image/png")

    row = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "run_id": None,
        "media_type": MediaType.IMAGE.value,
        "origin": MediaOrigin.GENERATED.value,
        "storage_key": upload.key,
        "mime_type": "image/png",
        "width": _DEMO_IMAGE_WIDTH,
        "height": _DEMO_IMAGE_HEIGHT,
        "duration_seconds": None,
        "source_url": None,
        "metadata": {
            "license": "CC0-1.0",
            "provenance": "synthetic",
            "generator": "placeholder-image",
            "note": "deterministic demo placeholder — no real model call",
            "size_bytes": upload.size_bytes,
            "checksum": upload.checksum,
            "storage_provider": upload.storage_provider,
        },
        "created_at": datetime.now(timezone.utc),
    }
    saved = await media_asset_service._asset_storage.save_asset(row)
    db_asset_id = saved["id"]
    # Map every sample asset id onto the single DB-backed demo image asset so the
    # remapped timeline only ever references a real, owned, renderable asset.
    asset_id_map = {10: db_asset_id, 11: db_asset_id}

    timeline = Timeline(
        id="demo-timeline",
        project_id=project_id,
        revision=0,
        segments=[
            MediaSegment(
                id="demo-seg-1",
                scene_id="scene-1",
                asset_id=db_asset_id,
                timeline_start_seconds=0.0,
                duration_seconds=4.0,
                fit_mode="cover",
                transition="fade",
            )
        ],
    )
    saved_timeline = await timeline_service.save_timeline(
        project_id=project_id,
        workspace_id=workspace_id,
        timeline=timeline,
        expected_revision=0,
    )

    # Create the run LAST: never a run pointing at incomplete content.
    run: PipelineRun = await create_demo_run(
        run_service=run_service,
        project_id=project_id,
        workspace_id=workspace_id,
    )

    return DemoShortSeedResult(
        run=run,
        project_id=project_id,
        timeline_id=saved_timeline.id,
        asset_id_map=asset_id_map,
    )
