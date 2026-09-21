"""Visual plan and visual asset generation trigger routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from creator_domain.models import TRIGGER_POLICY
from creator_service.run_service import run_service
from creator_service.task_dispatch_service import (
    cas_dispatch_with_rollback,
    dispatch_generate_scene_image,
    dispatch_generate_visual_plan,
)
from fastapi import APIRouter, Depends, HTTPException

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun


from shorts_api.routes.creator_runs_utils import (
    _has_active_tasks_for_run,
    validate_model_key,
)
from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.schemas.creator_runs import GenerateVisualPlanRequest
from shorts_api.schemas.creator_visuals import (
    GenerateVisualAssetsRequest,
    ImageTuningParams,
)

router = APIRouter(tags=["runs"])


@router.post("/runs/{run_id}/generate-visual-plan", status_code=202)
async def generate_visual_plan_trigger(
    run_id: int,
    request: GenerateVisualPlanRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, run = access
    if run.current_stage == "VISUAL_PLAN_GENERATING" and await _has_active_tasks_for_run(run.id):
        raise HTTPException(status_code=409, detail="Visual plan generation already in progress")

    allowed_stages = frozenset(stage.value for stage in TRIGGER_POLICY["generate_visual_plan"])
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_model_key(request.model_key, expected_category="llm")
    return await cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=allowed_stages,
        target_stage="VISUAL_PLAN_GENERATING",
        dispatcher=dispatch_generate_visual_plan,
        dispatcher_args={
            "run_id": run_id,
            "model_key": request.model_key,
            "style_preset": request.style_preset,
            "niche": request.niche,
        },
        run_service=run_service,
        rollback_stage=run.current_stage,
        rollback_restart_from=run.restart_from,
        enqueue_error_detail="Failed to enqueue visual plan generation task",
        quota_operation_type="llm",
        workspace_id=user.workspace_id,
    )


@router.post("/runs/{run_id}/generate-visual-assets", status_code=202)
async def generate_visual_assets_trigger(
    run_id: int,
    request: GenerateVisualAssetsRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, run = access
    if run.current_stage == "VISUAL_ASSET_GENERATING" and await _has_active_tasks_for_run(run.id):
        raise HTTPException(status_code=409, detail="Visual asset generation already in progress")

    allowed_stages = frozenset(stage.value for stage in TRIGGER_POLICY["generate_visual_assets"])
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_model_key(request.model_key, expected_category="image")
    return await cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=allowed_stages,
        target_stage="VISUAL_ASSET_GENERATING",
        dispatcher=dispatch_generate_scene_image,
        dispatcher_args={
            "run_id": run_id,
            "model_key": request.model_key,
            "scene_id": None,
            "prompt_override": None,
            "is_active": True,
            "image_params": request.image_params.model_dump() if request.image_params else None,
        },
        run_service=run_service,
        rollback_stage=run.current_stage,
        rollback_restart_from=run.restart_from,
        enqueue_error_detail="Failed to enqueue image generation task",
        quota_operation_type="image_gen",
        workspace_id=user.workspace_id,
    )
