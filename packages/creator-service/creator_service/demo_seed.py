"""Persist sample content before creating its paused timeline-review run."""

from __future__ import annotations

from dataclasses import dataclass

from creator_domain.models import MediaSegment, PipelineRun, Timeline

from creator_service.demo_short_flow import create_demo_run
from creator_service.media_asset_service import MediaAssetService
from creator_service.project_service import ProjectService
from creator_service.run_service import RunService
from creator_service.sample_project import sample_image_bytes
from creator_service.timeline_service import TimelineService


@dataclass(frozen=True, slots=True)
class DemoShortSeedResult:
    run: PipelineRun
    project_id: int
    timeline_id: str
    asset_id_map: dict[int, int]


async def seed_demo_short(
    *,
    workspace_id: int,
    project_service: ProjectService,
    media_asset_service: MediaAssetService,
    timeline_service: TimelineService,
    run_service: RunService,
) -> DemoShortSeedResult:
    project = await project_service.create_project(
        title="Demo Short", source_type="idea",
        idea_brief="A synthetic sample Short you can preview and edit.",
        workspace_id=workspace_id,
    )
    generated = await media_asset_service.create_generated_image_asset(
        workspace_id=workspace_id, project_id=project.id,
        filename="demo-generated-navy.png", data=sample_image_bytes((32, 48, 80)),
        metadata={
            "license": "CC0-1.0", "provenance": "synthetic", "generator": "offline-demo",
            "example_role": "generated-example", "contains_private_media": False,
        },
    )
    uploaded = await media_asset_service.create_image_asset(
        workspace_id=workspace_id, project_id=project.id,
        filename="demo-uploaded-example-cyan.png", data=sample_image_bytes((24, 192, 208)),
        content_type="image/png",
        metadata={
            "license": "CC0-1.0", "provenance": "synthetic", "generator": "offline-demo",
            "example_role": "uploaded-example", "contains_private_media": False,
            "note": "Locally generated synthetic uploaded example; not a real private upload.",
        },
    )
    timeline = Timeline(
        id=f"demo-timeline-{project.id}", project_id=project.id, revision=0,
        segments=[MediaSegment(
            id="demo-seg-1", scene_id="scene-1", asset_id=generated.id,
            timeline_start_seconds=0.0, duration_seconds=2.0,
            fit_mode="cover", transition="fade",
        ), MediaSegment(
            id="demo-seg-2", scene_id="scene-2", asset_id=uploaded.id,
            timeline_start_seconds=2.0, duration_seconds=2.0,
            fit_mode="cover", transition="cut",
        )],
    )
    saved_timeline = await timeline_service.save_timeline(
        project_id=project.id, workspace_id=workspace_id,
        timeline=timeline, expected_revision=0,
    )
    run = await create_demo_run(
        run_service=run_service, project_id=project.id, workspace_id=workspace_id,
    )
    return DemoShortSeedResult(
        run=run, project_id=project.id, timeline_id=saved_timeline.id,
        asset_id_map={10: generated.id, 11: uploaded.id},
    )
