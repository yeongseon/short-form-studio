"""Creator script generation routes."""

from fastapi import APIRouter

router = APIRouter()


@router.post("/projects/{project_id}/runs/{run_id}/script/generate")
def generate_script(project_id: str, run_id: str, data: dict = None) -> dict:
    """Generate script for a creator run."""
    return {"status": "placeholder", "script": ""}
