"""API-key authentication helpers."""

import hashlib

from creator_service.db import fetch_one
from creator_service.workspace_service import workspace_service
from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/healthz"})


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that keeps public-path behavior."""

    def __init__(self, app, *, api_key: str | None = None) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Always allow CORS preflight requests (OPTIONS with Origin header)
        if request.method == "OPTIONS" and "origin" in request.headers:
            return await call_next(request)

        # Always allow public paths
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        return await call_next(request)


async def get_current_user(request: Request) -> dict[str, str | int | None]:
    """Resolve user from api_keys table and workspace membership."""
    api_key = (
        request.headers.get("X-API-Key")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")

    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    key_row = await fetch_one(
        """
        SELECT user_id
        FROM api_keys
        WHERE key_hash = $1 AND revoked_at IS NULL
        LIMIT 1
        """,
        key_hash,
    )
    if key_row is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    user_id = key_row["user_id"]
    membership_row = await fetch_one(
        """
        SELECT workspace_id
        FROM workspace_members
        WHERE user_id = $1
        ORDER BY workspace_id ASC
        LIMIT 1
        """,
        user_id,
    )
    workspace_id = membership_row["workspace_id"] if membership_row is not None else None

    return {
        "user_id": user_id,
        "auth_provider": "api_key",
        "auth_subject": key_hash,
        "workspace_id": workspace_id,
    }


async def require_workspace_access(
    workspace_id: int,
    user: dict[str, str | int | None] = Depends(get_current_user),
) -> dict[str, str | int | None]:
    """Verify the user has access to the given workspace."""
    user_id = user.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=401, detail="Invalid user context")

    has_access = await workspace_service.check_access(workspace_id, user_id)
    if not has_access:
        raise HTTPException(status_code=403, detail="Workspace access denied")

    return user
