"""Routes for creator visual plan management."""
# pyright: reportMissingImports=false

import os
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

# Add packages to path for imports
_PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "../../../../..", "packages")
sys.path.insert(0, _PACKAGES_DIR)
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-service"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-domain"))

try:
    from creator_service.run_service import run_service
except ImportError:
    from run_service import run_service

try:
    from creator_service.visual_plan_service import visual_plan_service
except ImportError:
    from visual_plan_service import visual_plan_service

try:
    from creator_domain.models.visual_plan import VisualScene
except ImportError:
    from models.visual_plan import VisualScene

router = APIRouter(prefix="/runs/{run_id}/visual-plan", tags=["visual-plan"])


class ReplaceVisualPlanRequest(BaseModel):
    scenes: list[dict[str, object]]


@router.get("")
async def get_visual_plan(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    plan = await visual_plan_service.get_active_plan(run_id)
    if plan is None:
        raise HTTPException(
            status_code=404, detail="No visual plan found for this run"
        )

    return {
        "run_id": run_id,
        "version": plan.version,
        "scenes": [s.model_dump(mode="json") for s in plan.scenes],
    }


@router.put("")
async def replace_visual_plan(
    run_id: int, request: ReplaceVisualPlanRequest
) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    try:
        scenes = [VisualScene.model_validate(scene) for scene in request.scenes]
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plan = await visual_plan_service.save_plan(run_id, scenes)

    return {
        "run_id": run_id,
        "version": plan.version,
        "scenes": [s.model_dump(mode="json") for s in plan.scenes],
    }
