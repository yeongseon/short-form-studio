from __future__ import annotations

from functools import partial
import logging
from uuid import uuid4
from typing import TYPE_CHECKING

from creator_service.blocking_io import owned_operation, run_blocking, run_control
from creator_service.project_service import project_service
from creator_service.run_service import run_service
from creator_service.task_dispatch_service import dispatch_generate_scene_image
from creator_service.task_tracking_service import task_tracking_service
from creator_service.usage_service import reserve_owned_quota, cancel_owned_quota_reservation
from fastapi import APIRouter, Depends, HTTPException

from shorts_api.auth import CurrentUser, require_run_access
from shorts_api.routes.creator_runs_utils import validate_model_key, validate_path_id
from shorts_api.schemas.creator_visuals import GenerateSceneImageRequest, RegenerateSceneImageRequest

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun

router = APIRouter(tags=["runs"])
logger = logging.getLogger(__name__)


async def _enforce_run_quota(run_id: int, operation_type: str, workspace_id: int) -> int:
    run = await run_service.get_run(run_id, workspace_id=workspace_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    project = await project_service.get_project(run.project_id, workspace_id=workspace_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project_workspace_id = getattr(project, "workspace_id", None)
    if project_workspace_id is None:
        raise HTTPException(status_code=400, detail="Project workspace is not configured")
    return int(project_workspace_id)


async def _dispatch_image(run_id: int, workspace_id: int, **kwargs: object) -> str:
    task_id = str(uuid4())
    allowed, reason = await reserve_owned_quota(workspace_id, "image_gen", task_id)
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)
    published = False
    try:
        await task_tracking_service.record_task_pending(run_id, "generate_scene_image", task_id)
        returned_id = await run_blocking(partial(dispatch_generate_scene_image, run_id=run_id, task_id=task_id, **kwargs))
        published = True
        if returned_id != task_id:
            raise RuntimeError("Dispatch task ID mismatch")
        await task_tracking_service.promote_pending_to_queued(task_id)
        run = await run_service.get_run(run_id, workspace_id=workspace_id)
        if run is None or run.status == "cancelled":
            raise HTTPException(status_code=409, detail="Run was cancelled during dispatch")
        return task_id
    except Exception as exc:
        if published:
            try:
                await run_control(partial(__import__("celery_app").celery_app.control.revoke, task_id, terminate=True))
            except Exception:
                logger.warning("Failed to revoke image task", extra={"task_id": task_id}, exc_info=True)
            await task_tracking_service.mark_tasks_revoked([task_id])
        await cancel_owned_quota_reservation(task_id)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail="Failed to enqueue image generation task") from None


@router.post("/runs/{run_id}/visual-plan/scenes/{scene_id}/generate-image", status_code=202)
@owned_operation
async def generate_scene_image_endpoint(
    run_id: int, scene_id: str, request: GenerateSceneImageRequest | None = None,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    effective_request = request or GenerateSceneImageRequest()
    _, run = access
    validate_path_id(scene_id, "scene_id")
    allowed_stages = frozenset({"VISUAL_PLAN_REVIEW", "VISUAL_ASSET_GENERATING", "VISUAL_ASSET_REVIEW"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(status_code=409, detail=f"Run is in stage '{run.current_stage}', expected one of {sorted(allowed_stages)}")
    validate_model_key(effective_request.model_key, expected_category="image")
    workspace_id = await _enforce_run_quota(run_id, "image_gen", workspace_id=access[0].workspace_id)
    task_id = await _dispatch_image(
        run_id, workspace_id, model_key=effective_request.model_key,
        scene_id=scene_id, prompt_override=None, is_active=True,
        image_params=effective_request.image_params.model_dump() if effective_request.image_params else None,
    )
    return {"task_id": task_id, "run_id": run_id, "scene_id": scene_id, "current_stage": run.current_stage}


@router.post("/runs/{run_id}/visual-plan/scenes/{scene_id}/regenerate-image", status_code=202)
@owned_operation
async def regenerate_scene_image_endpoint(
    run_id: int, scene_id: str, request: RegenerateSceneImageRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    _, run = access
    validate_path_id(scene_id, "scene_id")
    allowed_stages = frozenset({"VISUAL_ASSET_REVIEW", "VISUAL_ASSET_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(status_code=409, detail=f"Run is in stage '{run.current_stage}', expected one of {sorted(allowed_stages)}")
    validate_model_key(request.model_key, expected_category="image")
    workspace_id = await _enforce_run_quota(run_id, "image_gen", workspace_id=access[0].workspace_id)
    task_id = await _dispatch_image(
        run_id, workspace_id, model_key=request.model_key,
        scene_id=scene_id, prompt_override=request.prompt_override, is_active=False,
        image_params=request.image_params.model_dump() if request.image_params else None,
    )
    return {"task_id": task_id, "run_id": run_id, "scene_id": scene_id, "current_stage": run.current_stage}
