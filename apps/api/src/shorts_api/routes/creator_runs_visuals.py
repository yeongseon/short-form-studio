"""Visual plan and visual asset generation trigger routes."""

from typing import Annotated

from creator_domain.models import TRIGGER_POLICY
from creator_service.run_service import run_service
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from shorts_api.routes.creator_runs_core import GenerateVisualPlanRequest
from shorts_api.routes.creator_runs_utils import (
    _has_active_tasks,
    cas_dispatch_with_rollback,
    dispatch_generate_scene_image,
    dispatch_generate_visual_plan,
    validate_model_key,
)

router = APIRouter(tags=["runs"])

_VALID_SAMPLERS = frozenset({
    "Euler a", "Euler", "LMS", "Heun", "DPM2", "DPM2 a",
    "DPM++ 2S a", "DPM++ 2M", "DPM++ SDE", "DPM++ 2M Karras",
    "DPM++ SDE Karras", "DPM++ 2M SDE Karras",
})


class ImageTuningParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: Annotated[int, Field(ge=10, le=50, description="Denoising steps")] = 25
    cfg_scale: Annotated[int | float, Field(ge=1, le=20, description="CFG scale")] = 7
    sampler_name: Annotated[
        str,
        Field(max_length=40, description="Sampler algorithm"),
    ] = "DPM++ 2M Karras"
    negative_prompt: Annotated[
        str,
        Field(max_length=1000, description="Negative prompt"),
    ] = ""


class GenerateVisualAssetsRequest(BaseModel):
    model_key: str = "sd15"
    image_params: ImageTuningParams | None = None


@router.post("/runs/{run_id}/generate-visual-plan", status_code=202)
async def generate_visual_plan_trigger(run_id: int, request: GenerateVisualPlanRequest) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.current_stage == "VISUAL_PLAN_GENERATING" and _has_active_tasks(run.active_task_id):
        raise HTTPException(status_code=409, detail="Visual plan generation already in progress")

    allowed_stages = frozenset(stage.value for stage in TRIGGER_POLICY["generate_visual_plan"])
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_model_key(request.model_key)
    return await cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=allowed_stages,
        target_stage="VISUAL_PLAN_GENERATING",
        dispatcher=dispatch_generate_visual_plan,
        dispatcher_args={
            "run_id": run_id,
            "model_key": request.model_key,
            "style_preset": request.style_preset,
        },
        run_service=run_service,
        rollback_stage=run.current_stage,
        rollback_restart_from=run.restart_from,
        enqueue_error_detail="Failed to enqueue visual plan generation task",
    )


@router.post("/runs/{run_id}/generate-visual-assets", status_code=202)
async def generate_visual_assets_trigger(
    run_id: int, request: GenerateVisualAssetsRequest
) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.current_stage == "VISUAL_ASSET_GENERATING" and _has_active_tasks(run.active_task_id):
        raise HTTPException(status_code=409, detail="Visual asset generation already in progress")

    allowed_stages = frozenset(stage.value for stage in TRIGGER_POLICY["generate_visual_assets"])
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_model_key(request.model_key)
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
    )
