"""Routes for creator visual plan management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from creator_domain.models import RunStage
from creator_domain.models.visual_plan import VisualScene
from creator_service.run_service import run_service
from creator_service.visual_plan_service import VersionConflictError, visual_plan_service
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.routes.creator_runs_utils import validate_path_id

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun

router = APIRouter(prefix="/runs/{run_id}/visual-plan", tags=["visual-plan"])

_VISUAL_PLAN_EDIT_STAGES = frozenset(
    {
        RunStage.VISUAL_PLAN_SETUP.value,
        RunStage.VISUAL_PLAN_REVIEW.value,
        RunStage.VISUAL_PLAN_GENERATING.value,
    }
)


class ReplaceVisualPlanRequest(BaseModel):
    scenes: list[dict[str, object]] = Field(min_length=1, max_length=200)


@router.get("")
async def get_visual_plan(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    _, run = access
    if run.current_stage not in _VISUAL_PLAN_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify visual plan in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_VISUAL_PLAN_EDIT_STAGES)}"
            ),
        )

    plan = await visual_plan_service.get_active_plan(run_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="No visual plan found for this run")

    return {
        "run_id": run_id,
        "version": plan.version,
        "scenes": [s.model_dump(mode="json") for s in plan.scenes],
    }


@router.put("")
async def replace_visual_plan(
    run_id: int,
    request: ReplaceVisualPlanRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    _, run = access
    if run.current_stage not in _VISUAL_PLAN_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify visual plan in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_VISUAL_PLAN_EDIT_STAGES)}"
            ),
        )

    try:
        scenes = [VisualScene.model_validate(scene) for scene in request.scenes]
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc

    plan = await visual_plan_service.save_plan(run_id, scenes)

    return {
        "run_id": run_id,
        "version": plan.version,
        "scenes": [s.model_dump(mode="json") for s in plan.scenes],
    }


class PatchSceneRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str | None = Field(default=None, max_length=2000)
    prompt_edited: bool | None = None
    prompt_source: Literal["auto_generated", "user_edited", "model_suggested"] | None = None
    style_tags: list[str] | None = None
    mood: str | None = None
    composition: str | None = None
    expected_version: int | None = None


@router.patch("/scenes/{scene_id}")
async def patch_scene(
    run_id: int,
    scene_id: str,
    request: PatchSceneRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    _, run = access
    validate_path_id(scene_id, "scene_id")
    if run.current_stage not in _VISUAL_PLAN_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify visual plan in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_VISUAL_PLAN_EDIT_STAGES)}"
            ),
        )

    # Build updates dict from non-None fields (exclude expected_version)
    updates = {
        k: v for k, v in request.model_dump(exclude={"expected_version"}).items() if v is not None
    }
    if not updates:
        raise HTTPException(status_code=400, detail="No patchable fields provided")

    try:
        plan = await visual_plan_service.patch_scene(
            run_id=run_id,
            scene_id=scene_id,
            updates=updates,
            expected_version=request.expected_version,
        )
    except (VersionConflictError, ValidationError) as exc:
        if isinstance(exc, VersionConflictError):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower() or "no active" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return {
        "run_id": run_id,
        "version": plan.version,
        "scenes": [s.model_dump(mode="json") for s in plan.scenes],
    }
