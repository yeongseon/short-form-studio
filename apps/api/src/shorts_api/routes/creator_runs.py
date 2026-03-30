"""Routes for creator run management."""
# pyright: reportMissingImports=false

import os
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Add packages to path for imports
_PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "../../../../..", "packages")
sys.path.insert(0, _PACKAGES_DIR)
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-service"))

try:
    from creator_service.project_service import project_service
    from creator_service.run_service import run_service
    from creator_service.stage_review_service import stage_review_service
except ImportError:
    from project_service import project_service
    from run_service import run_service
    from stage_review_service import stage_review_service


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


class GenerateScriptRequest(BaseModel):
    model_key: str = "qwen3-4b"
    instructions: str | None = None


class GenerateVisualPlanRequest(BaseModel):
    model_key: str = "qwen3-4b"
    style_preset: str | None = None
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

    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": "VISUAL_PLAN_GENERATING",
    }


class GenerateVisualAssetsRequest(BaseModel):
    model_key: str = "sd15"


def dispatch_generate_scene_image(
    run_id: int, model_key: str, scene_id: str | None, prompt_override: str | None, is_active: bool
) -> str:
    """Dispatch generate_scene_image Celery task. Returns task id.

    Separated into a function so tests can monkeypatch without importing Celery.
    """
    from importlib import import_module

    tasks = import_module("tasks.generate_scene_image")
    result = tasks.generate_scene_image.delay(
        run_id, scene_id=scene_id, model_key=model_key,
        prompt_override=prompt_override, is_active=is_active,
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

    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": "VISUAL_ASSET_GENERATING",
    }


class RegenerateSceneImageRequest(BaseModel):
    model_key: str = "sd15"
    prompt_override: str | None = None


@router.post(
    "/runs/{run_id}/visual-plan/scenes/{scene_id}/generate-image",
    status_code=202,
)
async def generate_scene_image_endpoint(
    run_id: int, scene_id: str
) -> dict[str, object]:
    """Generate an image for a single scene that hasn't been generated yet."""
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
            model_key="sd15",
            scene_id=scene_id,
            prompt_override=None,
            is_active=True,
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue image generation task",
        ) from None

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
        )
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Failed to enqueue image generation task",
        ) from None

    return {
        "task_id": task_id,
        "run_id": run_id,
        "scene_id": scene_id,
        "current_stage": run.current_stage,
    }
