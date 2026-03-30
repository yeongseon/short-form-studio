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
    # Lazy import — Celery is not available in test/API-only environments
    from importlib import import_module

    from celery import Celery  # noqa: F401

    tasks = import_module("tasks.generate_script")
    result = tasks.generate_script.delay(run_id, idea_brief, model_key, instructions)
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


class GenerateScriptRequest(BaseModel):
    model_key: str = "qwen3-4b"
    instructions: str | None = None

@router.post("/projects/{project_id}/runs", status_code=201)
async def create_run(project_id: int, request: CreateRunRequest) -> dict[str, object]:
    run = await run_service.create_run(
        project_id=project_id,
        model_defaults=request.model_defaults,
        style_preset=request.style_preset,
        metadata=request.metadata,
    )
    return run.model_dump(mode="json")


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


@router.post("/runs/{run_id}/generate-script", status_code=202)
async def generate_script_trigger(run_id: int, request: GenerateScriptRequest) -> dict[str, object]:
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Validate stage — only IDEA_READY and SCRIPT_REVIEW can trigger generation
    allowed = {"IDEA_READY", "SCRIPT_REVIEW"}
    if run.current_stage not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed)}",
        )

    # 3. Advance to SCRIPT_GENERATING
    #    - IDEA_READY → forward progression (advance_stage)
    #    - SCRIPT_REVIEW → re-generation (restart_run sets restart_from)
    try:
        if run.current_stage == "IDEA_READY":
            updated_run = await run_service.advance_stage(
                run_id=run_id, target_stage="SCRIPT_GENERATING"
            )
        else:
            updated_run = await run_service.restart_run(
                run_id=run_id, from_stage="SCRIPT_GENERATING"
            )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    # 4. Get project for idea_brief
    project = await project_service.get_project(updated_run.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    idea_brief = project.idea_brief or project.title or ""

    # 5. Dispatch Celery task
    task_id = dispatch_generate_script(
        run_id=run_id,
        idea_brief=idea_brief,
        model_key=request.model_key,
        instructions=request.instructions,
    )

    return {
        "task_id": task_id,
        "run_id": run_id,
        "current_stage": updated_run.current_stage,
    }
