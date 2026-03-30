"""Creator visual plan routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/visual-plan")
def get_visual_plan() -> dict:
    """Get visual plan placeholder."""
    return {"status": "placeholder", "plan": {}}
