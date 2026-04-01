"""Routes for creator run management."""
from typing import Any, Annotated

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from creator_service.audio_service import audio_service
from creator_service.project_service import project_service
from creator_service.render_service import render_service
from creator_service.run_service import run_service
from creator_service.stage_review_service import stage_review_service
from creator_service.subtitle_service import subtitle_service
from creator_service.visual_asset_service import visual_asset_service
from creator_service.script_service import script_service
from creator_service.visual_plan_service import visual_plan_service


def dispatch_generate_script(
    run_id: int, idea_brief: str, model_key: str, instructions: str | None
) -> str:
    """Dispatch generate_script Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_script")
    result = tasks.generate_script.delay(run_id, idea_brief, model_key, instructions)
    return str(result.id)

def dispatch_generate_visual_plan(
    run_id: int, model_key: str, style_preset: str | None
) -> str:
    """Dispatch generate_visual_plan Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_visual_plan")
    result = tasks.generate_visual_plan.delay(run_id, model_key, style_preset)
    return str(result.id)


def dispatch_generate_audio(run_id: int, tts_model: str, voice: str) -> str:
    """Dispatch generate_audio Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_audio")
    result = tasks.generate_audio.delay(run_id, tts_model=tts_model, voice=voice)
    return str(result.id)


def dispatch_generate_subtitles(run_id: int, subtitle_model: str, subtitle_format: str) -> str:
    """Dispatch generate_subtitles Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_subtitles")
    result = tasks.generate_subtitles.delay(run_id, subtitle_model=subtitle_model, subtitle_format=subtitle_format)
    return str(result.id)


def dispatch_render_video(run_id: int, render_profile: str) -> str:
    """Dispatch render_video Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.render_video")
    result = tasks.render_video.delay(run_id, render_profile=render_profile)
    return str(result.id)
router = APIRouter(tags=["runs"])


class CreateRunRequest(BaseModel):
    model_defaults: dict[str, str] | None = None
    style_preset: str = "default"
    metadata: dict[str, object] | None = None


class RestartRunRequest(BaseModel):
    stage: str


class ApproveScriptRequest(BaseModel):
    reviewer: str = "agent"
    notes: str | None = None

class ApproveVisualPlanRequest(BaseModel):
    reviewer: str = "agent"
    notes: str | None = None


class ApproveVisualAssetsRequest(BaseModel):
    reviewer: str = "agent"
    notes: str | None = None


class GenerateScriptRequest(BaseModel):
    model_key: str = "qwen3-4b"
    instructions: str | None = None


class GenerateVisualPlanRequest(BaseModel):
    model_key: str = "qwen3-4b"
    style_preset: str | None = None


class GenerateAudioRequest(BaseModel):
    tts_model: str = "qwen3-tts"
    voice: str = "default"


class GenerateSubtitlesRequest(BaseModel):
    subtitle_model: str = "whisper-small"
    subtitle_format: str = "srt"


class RenderRequest(BaseModel):
    render_profile: str = "shorts_default"


class UpdateModelDefaultsRequest(BaseModel):
    script_model: str | None = None
    image_model: str | None = None
    tts_model: str | None = None
    subtitle_model: str | None = None
    render_profile: str | None = None

@router.post("/projects/{project_id}/runs", status_code=201)
async def create_run(project_id: int, request: CreateRunRequest) -> dict[str, object]:
    run = await run_service.create_run(
        project_id=project_id,
        model_defaults=request.model_defaults,
        style_preset=request.style_preset,
        metadata=request.metadata,
    )
    return run.model_dump(mode="json")


@router.get("/projects/{project_id}/runs")
async def list_runs_for_project(project_id: int) -> dict[str, object]:
    runs = await run_service.list_runs_by_project(project_id)
    return {
        "runs": [r.model_dump(mode="json") for r in runs],
        "total": len(runs),
    }


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.model_dump(mode="json")


@router.post("/runs/{run_id}/restart")
async def restart_run(run_id: int, request: RestartRunRequest) -> dict[str, object]:
    try:
        run = await run_service.restart_run(run_id=run_id, from_stage=request.stage)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return run.model_dump(mode="json")


@router.post("/runs/{run_id}/approve-script")
async def approve_script(run_id: int, request: ApproveScriptRequest) -> dict[str, object]:
    try:
        updated_run = await stage_review_service.approve_and_advance(
            run_service=run_service,
            run_id=run_id,
            stage_name="SCRIPT_REVIEW",
            target_stage="VISUAL_PLAN_GENERATING",
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        if "conflict" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated_run.model_dump(mode="json")


@router.post("/runs/{run_id}/approve-visual-plan")
async def approve_visual_plan(run_id: int, request: ApproveVisualPlanRequest) -> dict[str, object]:
    try:
        updated_run = await stage_review_service.approve_and_advance(
            run_service=run_service,
            run_id=run_id,
            stage_name="VISUAL_PLAN_REVIEW",
            target_stage="VISUAL_ASSET_GENERATING",
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        if "conflict" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated_run.model_dump(mode="json")


@router.post("/runs/{run_id}/approve-visual-assets")
async def approve_visual_assets(run_id: int, request: ApproveVisualAssetsRequest) -> dict[str, object]:
    try:
        updated_run = await stage_review_service.approve_and_advance(
            run_service=run_service,
            run_id=run_id,
            stage_name="VISUAL_ASSET_REVIEW",
            target_stage="AUDIO_GENERATING",
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        if "conflict" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated_run.model_dump(mode="json")

@router.post("/runs/{run_id}/generate-script", status_code=202)
async def generate_script_trigger(run_id: int, request: GenerateScriptRequest) -> dict[str, object]:
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage — only IDEA_READY and SCRIPT_REVIEW can trigger generation
    allowed_stages = frozenset({"IDEA_READY", "SCRIPT_REVIEW"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    # 3. Resolve all preconditions BEFORE mutating state
    project = await project_service.get_project(run.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    idea_brief = project.idea_brief or project.title or ""

    # 4. Atomically advance to SCRIPT_GENERATING via CAS
    #    Prevents duplicate dispatch from concurrent requests.
    #    For SCRIPT_REVIEW restarts, also set restart_from.
    updates: dict[str, object] = {"current_stage": "SCRIPT_GENERATING"}
    if run.current_stage == "SCRIPT_REVIEW":
        updates["restart_from"] = "SCRIPT_GENERATING"

    ok, row = await run_service.storage.conditional_update_run(
        run_id, updates, expected_stages=allowed_stages,
    )
    if not ok:
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(
            status_code=409,
            detail=f"Stage conflict: run is now in '{row.get('current_stage')}'",
        )

    # 5. Dispatch Celery task — if this fails, roll back stage
    try:
        task_id = dispatch_generate_script(
            run_id=run_id,
            idea_brief=idea_brief,
            model_key=request.model_key,
            instructions=request.instructions,
        )
    except Exception:
        # Best-effort rollback: restore original stage so run isn't stuck
        await run_service.storage.conditional_update_run(
            run_id,
            {"current_stage": run.current_stage, "restart_from": run.restart_from},
            expected_stages=frozenset({"SCRIPT_GENERATING"}),
        )
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue script generation task",
        ) from None


    # Persist task_id for stop/revoke support
    await _append_task_id(run_id, task_id)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": "SCRIPT_GENERATING",
    }


@router.post("/runs/{run_id}/generate-visual-plan", status_code=202)
async def generate_visual_plan_trigger(run_id: int, request: GenerateVisualPlanRequest) -> dict[str, object]:
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage — SCRIPT_REVIEW (after approval) or VISUAL_PLAN_GENERATING (retry)
    allowed_stages = frozenset({"SCRIPT_REVIEW", "VISUAL_PLAN_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    # 3. Atomically advance to VISUAL_PLAN_GENERATING via CAS
    updates: dict[str, object] = {"current_stage": "VISUAL_PLAN_GENERATING"}
    if run.current_stage == "VISUAL_PLAN_GENERATING":
        updates["restart_from"] = "VISUAL_PLAN_GENERATING"

    ok, row = await run_service.storage.conditional_update_run(
        run_id, updates, expected_stages=allowed_stages,
    )
    if not ok:
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(
            status_code=409,
            detail=f"Stage conflict: run is now in '{row.get('current_stage')}'",
        )

    # 4. Dispatch Celery task — if this fails, roll back stage
    try:
        task_id = dispatch_generate_visual_plan(
            run_id=run_id,
            model_key=request.model_key,
            style_preset=request.style_preset,
        )
    except Exception:
        # Best-effort rollback: restore original stage so run isn't stuck
        await run_service.storage.conditional_update_run(
            run_id,
            {"current_stage": run.current_stage, "restart_from": run.restart_from},
            expected_stages=frozenset({"VISUAL_PLAN_GENERATING"}),
        )
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue visual plan generation task",
        ) from None


    # Persist task_id for stop/revoke support
    await _append_task_id(run_id, task_id)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": "VISUAL_PLAN_GENERATING",
    }



# ---------------------------------------------------------------------------
# Typed model for image tuning parameters.  Only safe AUTOMATIC1111 payload
# keys are accepted; extra keys are rejected by Pydantic (`extra="forbid"`).
# ---------------------------------------------------------------------------

_VALID_SAMPLERS = frozenset({
    "Euler a", "Euler", "LMS", "Heun", "DPM2", "DPM2 a",
    "DPM++ 2S a", "DPM++ 2M", "DPM++ SDE", "DPM++ 2M Karras",
    "DPM++ SDE Karras", "DPM++ 2M SDE Karras",
})


class ImageTuningParams(BaseModel):
    """Validated image generation parameters.

    Only exposes safe AUTOMATIC1111 knobs.  `extra='forbid'` ensures callers
    cannot inject dangerous keys (e.g. `prompt`, `alwayson_scripts`).
    """

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

def dispatch_generate_scene_image(
    run_id: int,
    model_key: str,
    scene_id: str | None,
    prompt_override: str | None,
    is_active: bool,
    image_params: dict[str, Any] | None = None,
) -> str:
    """Dispatch generate_scene_image Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_scene_image")
    result = tasks.generate_scene_image.delay(
        run_id, scene_id=scene_id, model_key=model_key,
        prompt_override=prompt_override, is_active=is_active,
        image_params=image_params,
    )
    return str(result.id)


@router.post("/runs/{run_id}/generate-visual-assets", status_code=202)
async def generate_visual_assets_trigger(
    run_id: int, request: GenerateVisualAssetsRequest
) -> dict[str, object]:
    """Generate images for all scenes in the approved visual plan."""
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage
    allowed_stages = frozenset({"VISUAL_PLAN_REVIEW", "VISUAL_ASSET_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    # 3. Atomically advance to VISUAL_ASSET_GENERATING via CAS
    updates: dict[str, object] = {"current_stage": "VISUAL_ASSET_GENERATING"}
    if run.current_stage == "VISUAL_ASSET_GENERATING":
        updates["restart_from"] = "VISUAL_ASSET_GENERATING"

    ok, row = await run_service.storage.conditional_update_run(
        run_id, updates, expected_stages=allowed_stages,
    )
    if not ok:
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(
            status_code=409,
            detail=f"Stage conflict: run is now in '{row.get('current_stage')}'",
        )

    # 4. Dispatch Celery task — if this fails, roll back stage
    try:
        task_id = dispatch_generate_scene_image(
            run_id=run_id,
            model_key=request.model_key,
            scene_id=None,  # all scenes
            prompt_override=None,
            is_active=True,
            image_params=request.image_params.model_dump() if request.image_params else None,
        )
    except Exception:
        # Best-effort rollback: restore original stage so run isn't stuck
        await run_service.storage.conditional_update_run(
            run_id,
            {"current_stage": run.current_stage, "restart_from": run.restart_from},
            expected_stages=frozenset({"VISUAL_ASSET_GENERATING"}),
        )
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue image generation task",
        ) from None


    # Persist task_id for stop/revoke support
    await _append_task_id(run_id, task_id)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": "VISUAL_ASSET_GENERATING",
    }


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
    """Generate an image for a single scene that hasn't been generated yet."""
    effective_request = request or GenerateSceneImageRequest()
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage
    allowed_stages = frozenset({"VISUAL_PLAN_REVIEW", "VISUAL_ASSET_GENERATING", "VISUAL_ASSET_REVIEW"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    # 3. Dispatch single-scene generation (no stage transition — stays in current stage)
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


    # Persist task_id for stop/revoke support
    await _append_task_id(run_id, task_id)
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
    """Regenerate an image for a single scene with optional model/prompt override.

    Regenerated assets are created as inactive by default so the user can
    compare versions before selecting the active one.
    """
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage — regeneration only allowed during asset review
    allowed_stages = frozenset({"VISUAL_ASSET_REVIEW", "VISUAL_ASSET_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    # 3. Dispatch single-scene regeneration (inactive by default)
    try:
        task_id = dispatch_generate_scene_image(
            run_id=run_id,
            model_key=request.model_key,
            scene_id=scene_id,
            prompt_override=request.prompt_override,
            is_active=False,  # regenerated assets are inactive until selected
            image_params=request.image_params.model_dump() if request.image_params else None,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue image generation task",
        ) from None


    # Persist task_id for stop/revoke support
    await _append_task_id(run_id, task_id)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "scene_id": scene_id,
        "current_stage": run.current_stage,
    }


@router.get("/runs/{run_id}/visual-assets")
async def list_visual_assets_by_run(run_id: int) -> dict[str, object]:
    """List all visual assets for a run, grouped by scene_id."""
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
    """List all asset versions for a single scene, newest first."""
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
    """Set the given asset as active for its scene, deactivating others."""
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Only allow selection during asset review
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
    """Trigger TTS audio generation for a run."""
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage — VISUAL_ASSET_REVIEW (after approval) or AUDIO_GENERATING (retry)
    allowed_stages = frozenset({"VISUAL_ASSET_REVIEW", "AUDIO_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    # 3. Atomically advance to AUDIO_GENERATING via CAS
    updates: dict[str, object] = {"current_stage": "AUDIO_GENERATING"}
    if run.current_stage == "AUDIO_GENERATING":
        updates["restart_from"] = "AUDIO_GENERATING"

    ok, row = await run_service.storage.conditional_update_run(
        run_id, updates, expected_stages=allowed_stages,
    )
    if not ok:
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(
            status_code=409,
            detail=f"Stage conflict: run is now in '{row.get('current_stage')}'",
        )

    # 4. Dispatch Celery task — if this fails, roll back stage
    try:
        task_id = dispatch_generate_audio(
            run_id=run_id,
            tts_model=request.tts_model,
            voice=request.voice,
        )
    except Exception:
        # Best-effort rollback: restore original stage so run isn't stuck
        await run_service.storage.conditional_update_run(
            run_id,
            {"current_stage": run.current_stage, "restart_from": run.restart_from},
            expected_stages=frozenset({"AUDIO_GENERATING"}),
        )
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue audio generation task",
        ) from None


    # Persist task_id for stop/revoke support
    await _append_task_id(run_id, task_id)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": "AUDIO_GENERATING",
    }


@router.post("/runs/{run_id}/generate-subtitles", status_code=202)
async def generate_subtitles_trigger(run_id: int, request: GenerateSubtitlesRequest) -> dict[str, object]:
    """Trigger subtitle generation for a run."""
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage — AUDIO_GENERATING (after audio done) or SUBTITLE_GENERATING (retry)
    allowed_stages = frozenset({"AUDIO_GENERATING", "SUBTITLE_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    # 3. Atomically advance to SUBTITLE_GENERATING via CAS
    updates: dict[str, object] = {"current_stage": "SUBTITLE_GENERATING"}
    if run.current_stage == "SUBTITLE_GENERATING":
        updates["restart_from"] = "SUBTITLE_GENERATING"

    ok, row = await run_service.storage.conditional_update_run(
        run_id, updates, expected_stages=allowed_stages,
    )
    if not ok:
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(
            status_code=409,
            detail="Stage conflict: run is now in '" + str(row.get('current_stage')) + "'",
        )

    # 4. Dispatch Celery task — if this fails, roll back stage
    try:
        task_id = dispatch_generate_subtitles(
            run_id=run_id,
            subtitle_model=request.subtitle_model,
            subtitle_format=request.subtitle_format,
        )
    except Exception:
        # Best-effort rollback: restore original stage so run isn't stuck
        await run_service.storage.conditional_update_run(
            run_id,
            {"current_stage": run.current_stage, "restart_from": run.restart_from},
            expected_stages=frozenset({"SUBTITLE_GENERATING"}),
        )
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue subtitle generation task",
        ) from None


    # Persist task_id for stop/revoke support
    await _append_task_id(run_id, task_id)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": "SUBTITLE_GENERATING",
    }


@router.post("/runs/{run_id}/render", status_code=202)
async def render_trigger(run_id: int, request: RenderRequest) -> dict[str, object]:
    """Trigger video rendering for a run."""
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage — SUBTITLE_GENERATING (after subtitles done) or RENDER_GENERATING (retry)
    allowed_stages = frozenset({"SUBTITLE_GENERATING", "RENDER_GENERATING"})
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    # 3. Atomically advance to RENDER_GENERATING via CAS
    updates: dict[str, object] = {"current_stage": "RENDER_GENERATING"}
    if run.current_stage == "RENDER_GENERATING":
        updates["restart_from"] = "RENDER_GENERATING"

    ok, row = await run_service.storage.conditional_update_run(
        run_id, updates, expected_stages=allowed_stages,
    )
    if not ok:
        if row is None:
            raise HTTPException(status_code=404, detail="Run not found")
        raise HTTPException(
            status_code=409,
            detail="Stage conflict: run is now in '" + str(row.get('current_stage')) + "'",
        )

    # 4. Dispatch Celery task — if this fails, roll back stage
    try:
        task_id = dispatch_render_video(
            run_id=run_id,
            render_profile=request.render_profile,
        )
    except Exception:
        # Best-effort rollback: restore original stage so run isn't stuck
        await run_service.storage.conditional_update_run(
            run_id,
            {"current_stage": run.current_stage, "restart_from": run.restart_from},
            expected_stages=frozenset({"RENDER_GENERATING"}),
        )
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue render task",
        ) from None


    # Persist task_id for stop/revoke support
    await _append_task_id(run_id, task_id)
    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": "RENDER_GENERATING",
    }


@router.get("/runs/{run_id}/preview")
async def get_preview(run_id: int) -> dict[str, object]:
    """Return latest video, audio, and subtitle artifact metadata for preview."""
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


# ---------------------------------------------------------------------------
# Storyboard endpoints (Phase 9 — Unified Paragraph Pipeline)
# ---------------------------------------------------------------------------


def dispatch_paragraph_audio(
    run_id: int, section_id: str, section_text: str, tts_model: str, voice: str
) -> str:
    """Dispatch generate_paragraph_audio Celery task. Returns task id."""
    from importlib import import_module

    tasks = import_module("tasks.generate_paragraph_audio")
    result = tasks.generate_paragraph_audio.delay(
        run_id, section_id=section_id, section_text=section_text,
        tts_model=tts_model, voice=voice,
    )
    return str(result.id)


def dispatch_paragraph_subtitles(
    run_id: int, section_id: str, audio_path: str,
    subtitle_model: str, subtitle_format: str,
) -> str:
    """Dispatch generate_paragraph_subtitles Celery task. Returns task id."""
    from importlib import import_module

    tasks = import_module("tasks.generate_paragraph_subtitles")
    result = tasks.generate_paragraph_subtitles.delay(
        run_id, section_id=section_id, audio_path=audio_path,
        subtitle_model=subtitle_model, subtitle_format=subtitle_format,
    )
    return str(result.id)


class ParagraphAudioRequest(BaseModel):
    tts_model: str = "qwen3-tts"
    voice: str = "default"


class ParagraphSubtitlesRequest(BaseModel):
    subtitle_model: str = "whisper-small"
    subtitle_format: str = "srt"


class BulkParagraphAudioRequest(BaseModel):
    tts_model: str = "qwen3-tts"
    voice: str = "default"


class BulkParagraphSubtitlesRequest(BaseModel):
    subtitle_model: str = "whisper-small"
    subtitle_format: str = "srt"


@router.get("/runs/{run_id}/storyboard")
async def get_storyboard(run_id: int) -> dict[str, object]:
    """Assemble the full storyboard for a run.

    Joins script sections + visual plan scenes + images + audio + subtitles
    into a unified per-paragraph view.
    """
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 1. Get active script draft → sections
    draft = await script_service.get_active_draft(run_id)
    if draft is None or not draft.structured_script:
        return {
            "run_id": run_id,
            "paragraphs": [],
            "render_ready": False,
            "total_paragraphs": 0,
            "ready_paragraphs": 0,
        }

    sections = draft.structured_script

    # 2. Get active visual plan → scenes keyed by section_id
    plan = await visual_plan_service.get_active_plan(run_id)
    scene_by_section: dict[str, Any] = {}
    if plan:
        for scene in plan.scenes:
            scene_by_section[scene.section_id] = scene

    # 3. Get visual assets grouped by scene_id
    grouped_assets = await visual_asset_service.list_by_run(run_id)

    # 4. Get per-paragraph audio artifacts keyed by section_id
    audio_artifacts = await audio_service.list_paragraph_audio(run_id)
    audio_by_section: dict[str, Any] = {}
    for a in audio_artifacts:
        if a.section_id and a.section_id not in audio_by_section:
            audio_by_section[a.section_id] = a

    # 5. Get per-paragraph subtitle artifacts keyed by section_id
    subtitle_artifacts = await subtitle_service.list_paragraph_subtitles(run_id)
    subtitle_by_section: dict[str, Any] = {}
    for s in subtitle_artifacts:
        if s.section_id and s.section_id not in subtitle_by_section:
            subtitle_by_section[s.section_id] = s

    # 6. Assemble paragraphs
    paragraphs: list[dict[str, object]] = []
    ready_count = 0

    for idx, section in enumerate(sections):
        scene = scene_by_section.get(section.section_id)
        scene_id = scene.scene_id if scene else None

        # Image: find active asset for this scene
        image_url: str | None = None
        image_asset_id: int | None = None
        if scene_id and scene_id in grouped_assets:
            for asset in grouped_assets[scene_id]:
                if asset.is_active:
                    image_url = asset.asset_path
                    image_asset_id = asset.id
                    break

        # Audio
        audio = audio_by_section.get(section.section_id)
        audio_url = audio.path if audio else None
        audio_duration = None  # Duration computed at render time
        audio_artifact_id = audio.id if audio else None

        # Subtitles
        subtitle = subtitle_by_section.get(section.section_id)
        subtitles_url = subtitle.path if subtitle else None
        subtitle_artifact_id = subtitle.id if subtitle else None

        # Status
        has_image = image_url is not None
        has_audio = audio_url is not None
        has_subtitles = subtitles_url is not None

        if has_image and has_audio and has_subtitles:
            status = "ready"
            ready_count += 1
        elif not has_image and not has_audio and not has_subtitles:
            status = "idle"
        else:
            status = "idle"  # partially done = still idle

        paragraphs.append({
            "section_id": section.section_id,
            "order": idx,
            "text": section.text,
            "display_text": section.display_text,
            "image_prompt": scene.prompt if scene else None,
            "image_url": image_url,
            "audio_url": audio_url,
            "audio_duration": audio_duration,
            "subtitles_url": subtitles_url,
            "subtitle_entries": None,
            "status": status,
            "stale_flags": None,
            "scene_id": scene_id,
            "image_asset_id": image_asset_id,
            "audio_artifact_id": audio_artifact_id,
            "subtitle_artifact_id": subtitle_artifact_id,
        })

    total = len(paragraphs)
    render_ready = total > 0 and ready_count == total

    return {
        "run_id": run_id,
        "paragraphs": paragraphs,
        "render_ready": render_ready,
        "total_paragraphs": total,
        "ready_paragraphs": ready_count,
    }


@router.post(
    "/runs/{run_id}/storyboard/paragraphs/{section_id}/generate-audio",
    status_code=202,
)
async def generate_paragraph_audio_endpoint(
    run_id: int, section_id: str, request: ParagraphAudioRequest | None = None
) -> dict[str, object]:
    """Dispatch per-paragraph TTS audio generation."""
    effective = request or ParagraphAudioRequest()
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Find section text
    draft = await script_service.get_active_draft(run_id)
    if draft is None or not draft.structured_script:
        raise HTTPException(status_code=400, detail="No script available")

    section_text: str | None = None
    for section in draft.structured_script:
        if section.section_id == section_id:
            section_text = section.text
            break

    if section_text is None:
        raise HTTPException(status_code=404, detail=f"Section '{section_id}' not found")

    try:
        task_id = dispatch_paragraph_audio(
            run_id=run_id,
            section_id=section_id,
            section_text=section_text,
            tts_model=effective.tts_model,
            voice=effective.voice,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue paragraph audio task",
        ) from None

    return {
        "task_id": task_id,
        "run_id": run_id,
        "section_id": section_id,
    }


@router.post(
    "/runs/{run_id}/storyboard/paragraphs/{section_id}/generate-subtitles",
    status_code=202,
)
async def generate_paragraph_subtitles_endpoint(
    run_id: int, section_id: str, request: ParagraphSubtitlesRequest | None = None
) -> dict[str, object]:
    """Dispatch per-paragraph subtitle generation."""
    effective = request or ParagraphSubtitlesRequest()
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Need audio to exist first
    audio = await audio_service.get_paragraph_audio(run_id, section_id)
    if audio is None:
        raise HTTPException(
            status_code=400,
            detail=f"No audio found for section '{section_id}'. Generate audio first.",
        )

    try:
        task_id = dispatch_paragraph_subtitles(
            run_id=run_id,
            section_id=section_id,
            audio_path=audio.path,
            subtitle_model=effective.subtitle_model,
            subtitle_format=effective.subtitle_format,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue paragraph subtitle task",
        ) from None

    return {
        "task_id": task_id,
        "run_id": run_id,
        "section_id": section_id,
    }


@router.post("/runs/{run_id}/storyboard/generate-all-audio", status_code=202)
async def generate_all_paragraph_audio(
    run_id: int, request: BulkParagraphAudioRequest | None = None
) -> dict[str, object]:
    """Dispatch TTS audio generation for ALL paragraphs in the script."""
    effective = request or BulkParagraphAudioRequest()
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    draft = await script_service.get_active_draft(run_id)
    if draft is None or not draft.structured_script:
        raise HTTPException(status_code=400, detail="No script available")

    task_ids: list[dict[str, str]] = []
    for section in draft.structured_script:
        try:
            tid = dispatch_paragraph_audio(
                run_id=run_id,
                section_id=section.section_id,
                section_text=section.text,
                tts_model=effective.tts_model,
                voice=effective.voice,
            )
            task_ids.append({"section_id": section.section_id, "task_id": tid})
        except Exception:
            task_ids.append({"section_id": section.section_id, "task_id": "", "error": "dispatch_failed"})

    return {
        "run_id": run_id,
        "tasks": task_ids,
        "total": len(task_ids),
    }


@router.post("/runs/{run_id}/storyboard/generate-all-subtitles", status_code=202)
async def generate_all_paragraph_subtitles(
    run_id: int, request: BulkParagraphSubtitlesRequest | None = None
) -> dict[str, object]:
    """Dispatch subtitle generation for ALL paragraphs that have audio."""
    effective = request or BulkParagraphSubtitlesRequest()
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Get all per-paragraph audio artifacts
    audio_artifacts = await audio_service.list_paragraph_audio(run_id)
    if not audio_artifacts:
        raise HTTPException(status_code=400, detail="No paragraph audio found. Generate audio first.")

    task_ids: list[dict[str, str]] = []
    for audio in audio_artifacts:
        if not audio.section_id:
            continue
        try:
            tid = dispatch_paragraph_subtitles(
                run_id=run_id,
                section_id=audio.section_id,
                audio_path=audio.path,
                subtitle_model=effective.subtitle_model,
                subtitle_format=effective.subtitle_format,
            )
            task_ids.append({"section_id": audio.section_id, "task_id": tid})
        except Exception:
            task_ids.append({"section_id": audio.section_id, "task_id": "", "error": "dispatch_failed"})

    return {
        "run_id": run_id,
        "tasks": task_ids,
        "total": len(task_ids),
    }


# ---------------------------------------------------------------------------
# Run lifecycle management (Phase 10 — Stop / Resume / Delete)
# ---------------------------------------------------------------------------


import json as _json
import os as _os
import shutil as _shutil


def _revoke_active_tasks(active_task_id: str | None) -> None:
    """Revoke all Celery tasks stored in active_task_id (JSON list or legacy single ID)."""
    if not active_task_id:
        return
    try:
        from celery_app import celery_app
        # Parse as JSON list; fall back to single ID for backwards compat
        try:
            task_ids = _json.loads(active_task_id)
            if isinstance(task_ids, str):
                task_ids = [task_ids]
        except (ValueError, TypeError):
            task_ids = [active_task_id]
        for tid in task_ids:
            if tid:
                celery_app.control.revoke(tid, terminate=True)
    except Exception:
        pass  # Best-effort: tasks may have already completed


async def _append_task_id(run_id: int, task_id: str) -> None:
    """Atomically append a task_id to the run's active_task_id JSON list.

    Uses a single UPDATE with jsonb to avoid read-modify-write races when
    multiple scene-image tasks are dispatched concurrently.
    """
    from creator_service.db import execute

    await execute(
        "UPDATE creator_runs "
        "SET active_task_id = ("
        "  COALESCE("
        "    CASE WHEN active_task_id IS NOT NULL "
        "         AND left(active_task_id, 1) = '[' "
        "    THEN active_task_id::jsonb "
        "    ELSE '[]'::jsonb "
        "    END, '[]'::jsonb"
        "  ) || to_jsonb($2::text)"
        ")::text "
        "WHERE id = $1",
        run_id,
        task_id,
    )

@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: int) -> dict[str, object]:
    """Stop a running pipeline. Revokes the active Celery task."""
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Revoke Celery task before updating DB
    _revoke_active_tasks(run.active_task_id)

    try:
        updated = await run_service.stop_run(run_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated.model_dump(mode="json")


@router.post("/runs/{run_id}/resume")
async def resume_run(run_id: int) -> dict[str, object]:
    """Resume a stopped/cancelled/failed run."""
    try:
        updated = await run_service.resume_run(run_id)
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated.model_dump(mode="json")


@router.post("/runs/{run_id}/go-back")
async def go_back(run_id: int) -> dict[str, object]:
    try:
        run = await run_service.go_back(run_id)
        return run.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch("/runs/{run_id}/model-defaults")
async def update_model_defaults(run_id: int, request: UpdateModelDefaultsRequest) -> dict[str, object]:
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No model defaults to update")
    try:
        run = await run_service.update_model_defaults(run_id, updates)
        return run.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int) -> dict[str, object]:
    """Delete a run. Revokes active task first if running."""
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Revoke any active task
    _revoke_active_tasks(run.active_task_id)

    deleted = await run_service.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")

    # Best-effort artifact cleanup
    _artifact_root = _os.getenv("ARTIFACT_ROOT", "data/artifacts")
    run_dir = _os.path.join(_artifact_root, str(run_id))
    if _os.path.isdir(run_dir):
        _shutil.rmtree(run_dir, ignore_errors=True)

    return {"deleted": True, "run_id": run_id}
