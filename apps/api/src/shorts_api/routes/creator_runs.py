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
