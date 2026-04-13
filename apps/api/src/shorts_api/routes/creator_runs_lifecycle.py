"""Run lifecycle and model defaults routes."""

import os
import shutil

from creator_service.run_service import run_service
from fastapi import APIRouter, HTTPException

from shorts_api.routes.creator_runs_core import UpdateModelDefaultsRequest
from shorts_api.routes.creator_runs_utils import _append_task_id, _revoke_active_tasks

router = APIRouter(tags=["runs"])
_APPEND_TASK_ID_HELPER = _append_task_id


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

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
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc
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
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    _revoke_active_tasks(run.active_task_id)

    deleted = await run_service.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")

    _artifact_root = os.getenv("ARTIFACT_ROOT", "data/artifacts")
    run_dir = os.path.join(_artifact_root, str(run_id))
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir, ignore_errors=True)

    return {"deleted": True, "run_id": run_id}
