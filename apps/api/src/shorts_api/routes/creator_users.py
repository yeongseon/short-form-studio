"""Routes for user identity — demonstrates get_current_user integration."""

from creator_domain.models import User
from fastapi import APIRouter, Depends

from shorts_api.auth import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(user: User = Depends(get_current_user)) -> dict:
    """Return the authenticated user's identity."""
    return user.model_dump(mode="json")
