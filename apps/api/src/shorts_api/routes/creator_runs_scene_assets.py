"""Scene image, asset listing, media generation, and preview routes."""

from creator_domain.models import TRIGGER_POLICY
from creator_service.audio_service import audio_service
from creator_service.render_service import render_service
from creator_service.run_service import run_service
from creator_service.subtitle_service import subtitle_service
from creator_service.visual_asset_service import visual_asset_service
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from shorts_api.routes.creator_runs_core import (
    GenerateAudioRequest,
    GenerateSubtitlesRequest,
    RenderRequest,
)
from shorts_api.routes.creator_runs_utils import (
    _append_task_id,
    cas_dispatch_with_rollback,
    dispatch_generate_audio,
    dispatch_generate_scene_image,
    dispatch_generate_subtitles,
    dispatch_render_video,
)
from shorts_api.routes.creator_runs_visuals import ImageTuningParams

router = APIRouter(tags=["runs"])


class RegenerateSceneImageRequest(BaseModel):
    model_key: str = "sd15"
    prompt_override: str | None = None
    image_params: ImageTuningParams | None = None


class GenerateSceneImageRequest(BaseModel):
    model_key: str = "sd15"
    image_params: ImageTuningParams | None = None


@router.post(
    "/runs/{run_id}/visual-plan/scenes/{scene_id}/generate-image",
    status_code=202,
)
async def generate_scene_image_endpoint(
    run_id: int, scene_id: str, request: GenerateSceneImageRequest | None = None
) -> dict[str, object]:
    effective_request = request or GenerateSceneImageRequest()
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    allowed_stages = frozenset({"VISUAL_PLAN_REVIEW", "VISUAL_ASSET_GENERATING", "VISUAL_ASSET_REVIEW"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    try:
        task_id = dispatch_generate_scene_image(
            run_id=run_id,
            model_key=effective_request.model_key,
            scene_id=scene_id,
            prompt_override=None,
            is_active=True,
            image_params=effective_request.image_params.model_dump() if effective_request.image_params else None,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue image generation task",
        ) from None

    await _append_task_id(run_id, task_id, run_service=run_service)
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
    run_id: int, scene_id: str, request: RegenerateSceneImageRequest
) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    allowed_stages = frozenset({"VISUAL_ASSET_REVIEW", "VISUAL_ASSET_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
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
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue image generation task",
        ) from None

    await _append_task_id(run_id, task_id, run_service=run_service)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "scene_id": scene_id,
        "current_stage": run.current_stage,
    }


@router.get("/runs/{run_id}/visual-assets")
async def list_visual_assets_by_run(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

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
async def list_visual_assets_by_scene(run_id: int, scene_id: str) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    assets = await visual_asset_service.list_by_scene(run_id, scene_id)
    return {
        "run_id": run_id,
        "scene_id": scene_id,
        "assets": [a.model_dump(mode="json") for a in assets],
        "total": len(assets),
    }


@router.post("/runs/{run_id}/visual-assets/{scene_id}/select/{asset_id}")
async def select_active_asset(run_id: int, scene_id: str, asset_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    allowed_stages = frozenset({"VISUAL_ASSET_REVIEW", "VISUAL_ASSET_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
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
async def generate_audio_trigger(run_id: int, request: GenerateAudioRequest) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    allowed_stages = frozenset(stage.value for stage in TRIGGER_POLICY["generate_audio"])
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

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
    )


@router.post("/runs/{run_id}/generate-subtitles", status_code=202)
async def generate_subtitles_trigger(run_id: int, request: GenerateSubtitlesRequest) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    allowed_stages = frozenset({"AUDIO_GENERATING", "SUBTITLE_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

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
    )


@router.post("/runs/{run_id}/render", status_code=202)
async def render_trigger(run_id: int, request: RenderRequest) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    allowed_stages = frozenset({"SUBTITLE_GENERATING", "RENDER_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

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
    )


@router.get("/runs/{run_id}/preview")
async def get_preview(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

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
        } if video else None,
        "audio": {
            "id": audio.id,
            "path": audio.path,
            "model_used": audio.model_used,
            "created_at": str(audio.created_at),
        } if audio else None,
        "subtitle": {
            "id": subtitle.id,
            "path": subtitle.path,
            "format": subtitle.format,
            "created_at": str(subtitle.created_at),
        } if subtitle else None,
    }
