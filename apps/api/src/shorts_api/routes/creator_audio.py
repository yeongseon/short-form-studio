"""Creator audio routes."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/audio")
def list_audio() -> dict:
    """List creator audio placeholder."""
    return {"status": "placeholder", "audio_files": []}
