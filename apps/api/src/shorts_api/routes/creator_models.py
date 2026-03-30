"""Creator models routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/models")
def list_models() -> dict:
    """Get available creator models."""
    return {"status": "placeholder", "models": []}
