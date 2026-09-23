import json

from creator_domain.exceptions import ConflictError
from creator_domain.models import EncodingProfile, OutputSpec, PipelineRun, RunStage
from creator_service.media_asset_service import media_asset_service
from creator_service.run_service import run_service
from creator_service.stage_review_service import stage_review_service
from creator_service.task_dispatch_service import cas_dispatch_with_rollback, dispatch_render_video
from creator_service.timeline_compiler import compile_timeline_to_render_plan
from creator_service.timeline_service import timeline_service
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from shorts_api.auth import CurrentUser, require_run_access

router = APIRouter(tags=["timeline"])


class ApproveTimelineRenderRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_revision: int = Field(ge=0, strict=True)


@router.post("/runs/{run_id}/approve-timeline-render", status_code=202)
async def approve_timeline_render(
    run_id: int,
    request: ApproveTimelineRenderRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, run = access
    if run.current_stage != RunStage.TIMELINE_REVIEW or run.status == "cancelled":
        raise ConflictError("Run must be awaiting timeline review")
    timeline = await timeline_service.load_timeline(
        project_id=run.project_id, workspace_id=user.workspace_id,
    )
    if timeline is None:
        raise HTTPException(status_code=404, detail="Timeline not found")
    if timeline.revision != request.expected_revision:
        raise ConflictError("Timeline revision changed; preview it before approving")
    await compile_timeline_to_render_plan(
        timeline, workspace_id=user.workspace_id,
        output_spec=OutputSpec.preset("short_vertical"),
        encoding_profile=EncodingProfile.by_name("preview"),
        asset_resolver=media_asset_service,
    )
    latest = await timeline_service.load_timeline(
        project_id=run.project_id, workspace_id=user.workspace_id,
    )
    if latest is None or latest.revision != request.expected_revision:
        raise ConflictError("Timeline revision changed; preview it before approving")
    metadata = {
        **(run.metadata or {}), "render_source": "timeline",
        "render_timeline_revision": request.expected_revision,
    }
    try:
        await stage_review_service.approve_and_advance(
            run_service=run_service, run_id=run_id,
            stage_name=RunStage.TIMELINE_REVIEW.value,
            target_stage=RunStage.RENDER_GENERATING.value,
            reviewer=str(user.user_id),
            notes=json.dumps({"timeline_id": timeline.id, "revision": timeline.revision}),
            workspace_id=user.workspace_id,
            extra_updates={"metadata_json": json.dumps(metadata)},
        )
    except ValueError as exc:
        raise ConflictError("Run changed during timeline approval") from exc
    return await cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=frozenset({RunStage.RENDER_GENERATING.value}),
        target_stage=RunStage.RENDER_GENERATING.value,
        dispatcher=dispatch_render_video,
        dispatcher_args={"run_id": run_id, "render_profile": "shorts_default"},
        run_service=run_service,
        rollback_stage=RunStage.TIMELINE_REVIEW.value,
        rollback_restart_from=run.restart_from,
        enqueue_error_detail="Failed to enqueue timeline render",
        workspace_id=user.workspace_id,
    )
