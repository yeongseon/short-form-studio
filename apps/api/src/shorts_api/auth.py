"""Optional API-key authentication middleware.

When the ``API_KEY`` environment variable is set, every request (except health
checks) must carry a matching key via the ``X-API-Key`` header or the standard
``Authorization: Bearer <key>`` header.  When the variable is unset the
middleware is a transparent pass-through so local development stays frictionless.
"""

import hmac
import logging
import os
from dataclasses import dataclass

from creator_service.db import fetch_one
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/healthz"})
_logger = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    workspace_id: int | None = None
    workspace_name: str | None = None


async def get_current_user(request: Request) -> CurrentUser:
    return getattr(request.state, "user", CurrentUser())


async def validate_workspace_header(request: Request) -> int | None:
    request_workspace_id_raw = request.headers.get("X-Workspace-Id")
    request_workspace_id: int | None = None
    if request_workspace_id_raw is not None:
        try:
            request_workspace_id = int(request_workspace_id_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid X-Workspace-Id header") from exc

    user = await get_current_user(request)
    user_workspace_id = getattr(user, "workspace_id", None)

    # Once merged with feat/user-workspace-model (#395), workspace_id is always populated on the user
    if (
        request_workspace_id is not None
        and user_workspace_id is not None
        and request_workspace_id != user_workspace_id
    ):
        raise HTTPException(status_code=403, detail="Forbidden")

    if request_workspace_id is not None:
        return request_workspace_id
    if user_workspace_id is not None:
        return user_workspace_id
    return None


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces an optional API key."""

    def __init__(self, app, *, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = api_key or os.getenv("API_KEY")

    async def _workspace_exists(self, workspace_id: int) -> bool:
        if not os.getenv("DATABASE_URL"):
            return False
        try:
            row = await fetch_one(
                "SELECT 1 AS exists FROM creator_projects WHERE workspace_id = $1 LIMIT 1",
                workspace_id,
            )
            return row is not None
        except Exception:
            _logger.warning(
                "Failed to validate workspace id against DB", extra={"workspace_id": workspace_id}
            )
            return False

    async def _resolve_workspace(self, api_key: str, request: Request) -> CurrentUser:
        if not api_key:
            return CurrentUser(workspace_id=None, workspace_name=None)
        requested_ws = request.headers.get("X-Workspace-Id")
        if requested_ws is None:
            return CurrentUser(workspace_id=None, workspace_name=None)

        try:
            ws_id = int(requested_ws)
        except ValueError:
            _logger.warning("Invalid X-Workspace-Id header", extra={"header": requested_ws})
            return CurrentUser(workspace_id=None, workspace_name=None)

        if not await self._workspace_exists(ws_id):
            _logger.warning("Workspace id from header not found", extra={"workspace_id": ws_id})
            return CurrentUser(workspace_id=None, workspace_name=None)

        return CurrentUser(workspace_id=ws_id, workspace_name=f"workspace-{ws_id}")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip auth when no key is configured (local dev)
        if not self._api_key:
            request.state.user = CurrentUser()  # No workspace enforcement in local dev
            return await call_next(request)

        # Always allow CORS preflight requests (OPTIONS with Origin header)
        if request.method == "OPTIONS" and "origin" in request.headers:
            request.state.user = CurrentUser()
            return await call_next(request)

        # Always allow public paths
        if request.url.path in _PUBLIC_PATHS:
            request.state.user = CurrentUser()
            return await call_next(request)

        # Docs paths go through normal auth when API_KEY is set
        # (they were removed from _PUBLIC_PATHS so they're not auto-allowed)

        # Check header only (never accept keys via query params to avoid log leakage)
        provided = request.headers.get("X-API-Key")
        if not provided:
            # Fall back to Authorization: Bearer <key>
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                provided = auth_header[7:]  # len("Bearer ") == 7
        if not provided or not hmac.compare_digest(provided, self._api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        request.state.user = await self._resolve_workspace(provided, request)
        return await call_next(request)
