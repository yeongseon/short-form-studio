"""Run lifecycle and model defaults routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from creator_service.artifact_download_service import artifact_download_service
from creator_service.run_service import ConflictError, run_service
from fastapi import APIRouter, Depends, HTTPException

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun

from shorts_api.routes.creator_runs_core import UpdateModelDefaultsRequest
from shorts_api.routes.creator_runs_utils import (
    _revoke_active_tasks_for_run,
    validate_model_defaults,
)
from shorts_api.auth import CurrentUser, require_run_access

router = APIRouter(tags=["runs"])


@router.post("/runs/{run_id}/stop")
async def stop_run(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    user, run = access

    try:
        updated = await run_service.stop_run(run_id, workspace_id=user.workspace_id)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    await _revoke_active_tasks_for_run(run.id)

    return updated.model_dump(mode="json")


@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    user, _ = access
    try:
        updated = await run_service.resume_run(run_id, workspace_id=user.workspace_id)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated.model_dump(mode="json")


@router.post("/runs/{run_id}/go-back")
async def go_back(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    user, _ = access
    try:
        run = await run_service.go_back(run_id, workspace_id=user.workspace_id)
        return run.model_dump(mode="json")
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc


@router.patch("/runs/{run_id}/model-defaults")
async def update_model_defaults(
    run_id: int,
    request: UpdateModelDefaultsRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, _ = access
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No model defaults to update")
    validate_model_defaults(updates)
    try:
        run = await run_service.update_model_defaults(
            run_id,
            updates,
            workspace_id=user.workspace_id,
        )
        return run.model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/runs/{run_id}")
async def delete_run(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    user, run = access

    try:
        deleted = await run_service.delete_run(run_id, workspace_id=user.workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")

    await _revoke_active_tasks_for_run(run.id)
    await artifact_download_service.delete_artifacts_for_run(run_id)

    return {"deleted": True, "run_id": run_id}
