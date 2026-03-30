"""Creator assets routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/assets")
def list_assets() -> dict:
    """List creator assets placeholder."""
    return {"status": "placeholder", "assets": []}
