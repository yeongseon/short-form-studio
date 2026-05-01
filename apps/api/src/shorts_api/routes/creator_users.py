"""Routes for user identity - demonstrates get_current_user integration."""

from fastapi import APIRouter, Depends

from shorts_api.auth import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(
    user: dict[str, str | int | None] = Depends(get_current_user),  # noqa: B008
) -> dict[str, str | int | None]:
    """Return the authenticated user's identity."""
    return user
