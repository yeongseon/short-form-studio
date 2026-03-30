"""Creator projects routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/projects")
def list_projects() -> dict:
    """List all creator projects."""
    return {"status": "placeholder", "projects": []}


@router.post("/projects")
def create_project(data: dict) -> dict:
    """Create a new creator project."""
    return {"status": "placeholder", "project_id": None}
