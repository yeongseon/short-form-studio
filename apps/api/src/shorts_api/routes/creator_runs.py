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
    from creator_service.run_service import run_service
    from creator_service.stage_review_service import stage_review_service
except ImportError:
    from run_service import run_service
    from stage_review_service import stage_review_service

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
    # 1. Check run exists
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # 2. Check run is in SCRIPT_REVIEW stage
    if run.current_stage != "SCRIPT_REVIEW":
        raise HTTPException(
            status_code=400,
            detail=f"Run is in stage '{run.current_stage}', expected 'SCRIPT_REVIEW'",
        )

    # 3. Record approval
    try:
        await stage_review_service.record_approval(
            run_id=run_id,
            stage_name="SCRIPT_REVIEW",
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 4. Advance stage: SCRIPT_REVIEW → VISUAL_PLAN_GENERATING
    try:
        updated_run = await run_service.advance_stage(
            run_id=run_id, target_stage="VISUAL_PLAN_GENERATING"
        )
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to advance stage: {exc}") from exc

    return updated_run.model_dump(mode="json")
