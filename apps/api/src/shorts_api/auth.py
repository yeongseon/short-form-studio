"""Optional API-key authentication middleware.

When the ``API_KEY`` environment variable is set, every request (except health
checks) must carry a matching key via the ``X-API-Key`` header or the standard
``Authorization: Bearer <key>`` header.  When the variable is unset the
middleware is a transparent pass-through so local development stays frictionless.
"""

import hmac
import hashlib
import logging
import os
from dataclasses import dataclass

from creator_service.db import fetch_one
from fastapi import Request
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
    user = await get_current_user(request)
    return getattr(user, "workspace_id", None)


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces an optional API key."""

    def __init__(self, app, *, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = api_key or os.getenv("API_KEY")

    async def _resolve_user(self, api_key: str) -> CurrentUser:
        if not api_key or not os.getenv("DATABASE_URL"):
            return CurrentUser()

        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        api_key_row = await fetch_one(
            """
            SELECT user_id
            FROM api_keys
            WHERE key_hash = $1
              AND revoked_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            key_hash,
        )
        if api_key_row is None:
            return CurrentUser()

        user_id = int(api_key_row["user_id"])

        membership_row = await fetch_one(
            """
            SELECT wm.workspace_id, w.name AS workspace_name
            FROM workspace_members wm
            LEFT JOIN workspaces w ON w.id = wm.workspace_id
            WHERE wm.user_id = $1
            ORDER BY wm.workspace_id ASC
            LIMIT 1
            """,
            user_id,
        )
        if membership_row is None:
            return CurrentUser()

        return CurrentUser(
            workspace_id=int(membership_row["workspace_id"]),
            workspace_name=membership_row.get("workspace_name"),
        )

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

        request.state.user = await self._resolve_user(provided)
        if getattr(request.state.user, "workspace_id", None) is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)
