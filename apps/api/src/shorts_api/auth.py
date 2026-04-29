"""Optional API-key authentication middleware.

When the ``API_KEY`` environment variable is set, every request (except health
checks) must carry a matching key via the ``X-API-Key`` header or the standard
``Authorization: Bearer <key>`` header.  When the variable is unset the
middleware is a transparent pass-through so local development stays frictionless.
"""

import hmac
import os

from creator_domain.models import User
from creator_service.workspace_service import workspace_service
from creator_service.user_service import user_service
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/healthz"})


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces an optional API key."""

    def __init__(self, app, *, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = api_key or os.getenv("API_KEY")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip auth when no key is configured (local dev)
        if not self._api_key:
            return await call_next(request)

        # Always allow CORS preflight requests (OPTIONS with Origin header)
        if request.method == "OPTIONS" and "origin" in request.headers:
            return await call_next(request)

        # Always allow public paths
        if request.url.path in _PUBLIC_PATHS:
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

        return await call_next(request)


async def get_current_user(request: Request) -> User:
    """Resolve user identity after API key middleware has authenticated the request.

    In production (API_KEY is set), all requests are attributed to the system user.
    The X-User-Email header is ONLY honoured when API_KEY is unset (local dev)
    because any caller who can set HTTP headers could impersonate another user.
    JWT/OAuth support will replace this in a future PR.
    """
    api_key_configured = bool(os.getenv("API_KEY"))

    # In production, always use the system user — X-User-Email is untrusted
    # when the only auth is a shared API key.
    if api_key_configured:
        return await user_service.create_or_get_user(
            email="system@short-form-studio.local",
            name="System",
            auth_provider="api_key",
            auth_subject="system",
        )

    # Dev mode: allow X-User-Email for convenience
    user_email = request.headers.get("X-User-Email")
    if user_email:
        return await user_service.create_or_get_user(
            email=user_email,
            auth_provider="api_key",
            auth_subject=user_email,
        )

    return await user_service.create_or_get_user(
        email="system@short-form-studio.local",
        name="System",
        auth_provider="api_key",
        auth_subject="system",
    )


async def require_workspace_access(
    workspace_id: int,
    user: User = Depends(get_current_user),
) -> User:
    """Verify the user has access to the given workspace.

    In production (shared API-key auth, system user), workspace access is
    implicitly granted since there is only one system identity.
    When per-user identity is enabled (JWT/OAuth, future PR), this will
    check workspace membership.
    """
    if os.getenv("API_KEY") and user.auth_subject == "system":
        return user

    has_access = await workspace_service.check_access(workspace_id, user.id)
    if not has_access:
        raise HTTPException(status_code=403, detail="Workspace access denied")

    return user
