"""Creator runs routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/projects/{project_id}/runs")
def list_runs(project_id: str) -> dict:
    """List runs for a creator project."""
    return {"status": "placeholder", "runs": []}
