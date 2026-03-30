"""Creator render routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/render")
def get_render_status() -> dict:
    """Get render status placeholder."""
    return {"status": "placeholder", "render_id": None}
