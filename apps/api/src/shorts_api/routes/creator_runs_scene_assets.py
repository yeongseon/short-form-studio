"""Scene image, asset listing, media generation, and preview routes."""

from __future__ import annotations

from typing import TYPE_CHECKING
import logging

from creator_domain.models import TRIGGER_POLICY
from creator_service.audio_service import audio_service
from creator_service.project_service import project_service
from creator_service.render_service import render_service
from creator_service.run_service import run_service
from creator_service.subtitle_service import subtitle_service
from creator_service.task_dispatch_service import (
    cas_dispatch_with_rollback,
    dispatch_generate_audio,
    dispatch_generate_scene_image,
    dispatch_generate_subtitles,
    dispatch_render_video,
)
from creator_service.task_tracking_service import task_tracking_service
from creator_service.visual_asset_service import visual_asset_service
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun


from shorts_api.routes.creator_runs_core import (
    GenerateAudioRequest,
    GenerateSubtitlesRequest,
    RenderRequest,
)
from shorts_api.routes.creator_runs_utils import (
    _has_active_tasks_for_run,
    validate_model_key,
    validate_path_id,
    validate_render_profile,
)
from shorts_api.routes.creator_runs_visuals import ImageTuningParams
from shorts_api.auth import CurrentUser, require_run_access

router = APIRouter(tags=["runs"])


logger = logging.getLogger(__name__)

async def _enforce_run_quota(run_id: int, operation_type: str, workspace_id: int) -> int:
    from creator_service.usage_service import check_workspace_quota

    run = await run_service.get_run(run_id, workspace_id=workspace_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    project = await project_service.get_project(run.project_id, workspace_id=workspace_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project_workspace_id = getattr(project, "workspace_id", None)
    if project_workspace_id is None:
        raise HTTPException(status_code=400, detail="Project workspace is not configured")

    allowed, reason = await check_workspace_quota(
        int(project_workspace_id), operation_type=operation_type
    )
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)
    return int(project_workspace_id)


class RegenerateSceneImageRequest(BaseModel):
    model_key: str = "sd15"
    prompt_override: str | None = Field(default=None, max_length=2000)
    image_params: ImageTuningParams | None = None


class GenerateSceneImageRequest(BaseModel):
    model_key: str = "sd15"
    image_params: ImageTuningParams | None = None


@router.post(
    "/runs/{run_id}/visual-plan/scenes/{scene_id}/generate-image",
    status_code=202,
)
async def generate_scene_image_endpoint(
    run_id: int,
    scene_id: str,
    request: GenerateSceneImageRequest | None = None,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    effective_request = request or GenerateSceneImageRequest()
    _, run = access
    validate_path_id(scene_id, "scene_id")

    allowed_stages = frozenset(
        {"VISUAL_PLAN_REVIEW", "VISUAL_ASSET_GENERATING", "VISUAL_ASSET_REVIEW"}
    )
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_model_key(effective_request.model_key, expected_category="image")
    workspace_id = await _enforce_run_quota(
        run_id, "image_gen", workspace_id=access[0].workspace_id
    )
    try:
        task_id = dispatch_generate_scene_image(
            run_id=run_id,
            model_key=effective_request.model_key,
            scene_id=scene_id,
            prompt_override=None,
            is_active=True,
            image_params=effective_request.image_params.model_dump()
            if effective_request.image_params
            else None,
        )
    except Exception:
        from creator_service.usage_service import cancel_workspace_quota_reservation

        await cancel_workspace_quota_reservation(workspace_id, "image_gen")
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue image generation task",
        ) from None

    try:
        await task_tracking_service.record_task_queued(run_id, "generate_scene_image", task_id)
    except Exception:
        logger.error("Failed to track task %s for run %d — revoking orphan", task_id, run_id, exc_info=True)
        try:
            __import__("celery_app").celery_app.control.revoke(task_id, terminate=True)
        except Exception:
            logger.error("Failed to revoke orphan task %s", task_id, exc_info=True)
        from creator_service.usage_service import cancel_workspace_quota_reservation
        await cancel_workspace_quota_reservation(workspace_id, "image_gen")
        raise HTTPException(status_code=503, detail="Task tracking failed") from None
    return {
        "task_id": task_id,
        "run_id": run_id,
        "scene_id": scene_id,
        "current_stage": run.current_stage,
    }


@router.post(
    "/runs/{run_id}/visual-plan/scenes/{scene_id}/regenerate-image",
    status_code=202,
)
async def regenerate_scene_image_endpoint(
    run_id: int,
    scene_id: str,
    request: RegenerateSceneImageRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    _, run = access
    validate_path_id(scene_id, "scene_id")

    allowed_stages = frozenset({"VISUAL_ASSET_REVIEW", "VISUAL_ASSET_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_model_key(request.model_key, expected_category="image")
    workspace_id = await _enforce_run_quota(
        run_id, "image_gen", workspace_id=access[0].workspace_id
    )
    try:
        task_id = dispatch_generate_scene_image(
            run_id=run_id,
            model_key=request.model_key,
            scene_id=scene_id,
            prompt_override=request.prompt_override,
            is_active=False,
            image_params=request.image_params.model_dump() if request.image_params else None,
        )
    except Exception:
        from creator_service.usage_service import cancel_workspace_quota_reservation

        await cancel_workspace_quota_reservation(workspace_id, "image_gen")
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue image generation task",
        ) from None

    try:
        await task_tracking_service.record_task_queued(run_id, "generate_scene_image", task_id)
    except Exception:
        logger.error("Failed to track task %s for run %d — revoking orphan", task_id, run_id, exc_info=True)
        try:
            __import__("celery_app").celery_app.control.revoke(task_id, terminate=True)
        except Exception:
            logger.error("Failed to revoke orphan task %s", task_id, exc_info=True)
        from creator_service.usage_service import cancel_workspace_quota_reservation
        await cancel_workspace_quota_reservation(workspace_id, "image_gen")
        raise HTTPException(status_code=503, detail="Task tracking failed") from None
    return {
        "task_id": task_id,
        "run_id": run_id,
        "scene_id": scene_id,
        "current_stage": run.current_stage,
    }


@router.get("/runs/{run_id}/visual-assets")
async def list_visual_assets_by_run(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    _ = access

    grouped = await visual_asset_service.list_by_run(run_id)
    return {
        "run_id": run_id,
        "scenes": {
            scene_id: [a.model_dump(mode="json") for a in assets]
            for scene_id, assets in grouped.items()
        },
        "total_scenes": len(grouped),
        "total_assets": sum(len(assets) for assets in grouped.values()),
    }


@router.get("/runs/{run_id}/visual-assets/{scene_id}")
async def list_visual_assets_by_scene(
    run_id: int,
    scene_id: str,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    _ = access
    validate_path_id(scene_id, "scene_id")

    assets = await visual_asset_service.list_by_scene(run_id, scene_id)
    return {
        "run_id": run_id,
        "scene_id": scene_id,
        "assets": [a.model_dump(mode="json") for a in assets],
        "total": len(assets),
    }


@router.post("/runs/{run_id}/visual-assets/{scene_id}/select/{asset_id}")
async def select_active_asset(
    run_id: int,
    scene_id: str,
    asset_id: int,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    _, run = access
    validate_path_id(scene_id, "scene_id")

    allowed_stages = frozenset({"VISUAL_ASSET_REVIEW", "VISUAL_ASSET_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    try:
        asset = await visual_asset_service.select_active(run_id, scene_id, asset_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return asset.model_dump(mode="json")


@router.post("/runs/{run_id}/generate-audio", status_code=202)
async def generate_audio_trigger(
    run_id: int,
    request: GenerateAudioRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, run = access
    if run.current_stage == "AUDIO_GENERATING" and await _has_active_tasks_for_run(run.id):
        raise HTTPException(status_code=409, detail="Audio generation already in progress")

    allowed_stages = frozenset(stage.value for stage in TRIGGER_POLICY["generate_audio"])
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_model_key(request.tts_model, expected_category="tts")
    return await cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=allowed_stages,
        target_stage="AUDIO_GENERATING",
        dispatcher=dispatch_generate_audio,
        dispatcher_args={
            "run_id": run_id,
            "tts_model": request.tts_model,
            "voice": request.voice,
        },
        run_service=run_service,
        rollback_stage=run.current_stage,
        rollback_restart_from=run.restart_from,
        enqueue_error_detail="Failed to enqueue audio generation task",
        quota_operation_type="tts",
        workspace_id=user.workspace_id,
    )


@router.post("/runs/{run_id}/generate-subtitles", status_code=202)
async def generate_subtitles_trigger(
    run_id: int,
    request: GenerateSubtitlesRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, run = access
    if run.current_stage == "SUBTITLE_GENERATING" and await _has_active_tasks_for_run(run.id):
        raise HTTPException(status_code=409, detail="Subtitle generation already in progress")

    allowed_stages = frozenset({"AUDIO_GENERATING", "SUBTITLE_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_model_key(request.subtitle_model, expected_category="stt")
    return await cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=allowed_stages,
        target_stage="SUBTITLE_GENERATING",
        dispatcher=dispatch_generate_subtitles,
        dispatcher_args={
            "run_id": run_id,
            "subtitle_model": request.subtitle_model,
            "subtitle_format": request.subtitle_format,
        },
        run_service=run_service,
        rollback_stage=run.current_stage,
        rollback_restart_from=run.restart_from,
        enqueue_error_detail="Failed to enqueue subtitle generation task",
        quota_operation_type="stt",
        workspace_id=user.workspace_id,
    )


@router.post("/runs/{run_id}/render", status_code=202)
async def render_trigger(
    run_id: int,
    request: RenderRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, run = access
    if run.current_stage == "RENDER_GENERATING" and await _has_active_tasks_for_run(run.id):
        raise HTTPException(status_code=409, detail="Render already in progress")

    allowed_stages = frozenset({"SUBTITLE_GENERATING", "RENDER_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    validate_render_profile(request.render_profile)
    return await cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=allowed_stages,
        target_stage="RENDER_GENERATING",
        dispatcher=dispatch_render_video,
        dispatcher_args={
            "run_id": run_id,
            "render_profile": request.render_profile,
        },
        run_service=run_service,
        rollback_stage=run.current_stage,
        rollback_restart_from=run.restart_from,
        enqueue_error_detail="Failed to enqueue render task",
        quota_operation_type="render",
        workspace_id=user.workspace_id,
    )


@router.get("/runs/{run_id}/preview")
async def get_preview(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    _, run = access

    video = await render_service.get_latest(run_id)
    audio = await audio_service.get_latest(run_id)
    subtitle = await subtitle_service.get_latest(run_id)

    return {
        "run_id": run_id,
        "current_stage": run.current_stage,
        "video": {
            "id": video.id,
            "path": video.path,
            "render_profile": video.render_profile,
            "created_at": str(video.created_at),
        }
        if video
        else None,
        "audio": {
            "id": audio.id,
            "path": audio.path,
            "model_used": audio.model_used,
            "created_at": str(audio.created_at),
        }
        if audio
        else None,
        "subtitle": {
            "id": subtitle.id,
            "path": subtitle.path,
            "format": subtitle.format,
            "created_at": str(subtitle.created_at),
        }
        if subtitle
        else None,
    }
