"""API-key identity middleware.

When a request provides an API key (``X-API-Key`` or ``Authorization: Bearer``),
the middleware resolves user identity from ``api_keys`` and workspace membership
from ``workspace_members``.
"""

import contextvars
import hashlib
import logging
from dataclasses import dataclass

from fastapi import Request
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/healthz"})
logger = logging.getLogger(__name__)
_current_user_ctx: contextvars.ContextVar["CurrentUser | None"] = contextvars.ContextVar(
    "current_user",
    default=None,
)


@dataclass
class CurrentUser:
    user_id: int | None = None
    workspace_id: int | None = None
    workspace_name: str | None = None


class _FetchOneResult:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _AsyncpgSessionAdapter:
    def __init__(self, connection) -> None:
        self._connection = connection

    async def execute(self, query, params: dict[str, object]):
        row = await self._connection.fetchrow(str(query), params["h"])
        if row is None:
            return _FetchOneResult(None)
        return _FetchOneResult((row.get("user_id"),))


async def _resolve_user_id_from_api_key(api_key: str, db_session) -> str | None:
    """Resolve user_id from API key via api_keys table."""
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    result = await db_session.execute(
        text("SELECT user_id FROM api_keys WHERE key_hash = :h AND revoked_at IS NULL"),
        {"h": key_hash},
    )
    row = result.fetchone()
    return row[0] if row else None


async def get_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if isinstance(user, CurrentUser) and user.user_id is not None:
        return user

    context_user = _current_user_ctx.get()
    if isinstance(context_user, CurrentUser) and context_user.user_id is not None:
        return context_user

    raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def require_current_user(request: Request) -> CurrentUser:
    return await get_current_user(request)


async def optional_current_user(request: Request) -> CurrentUser | None:
    """Return authenticated user or None. For routes with optional auth."""
    user = getattr(request.state, "user", None)
    if isinstance(user, CurrentUser) and user.user_id is not None:
        return user
    context_user = _current_user_ctx.get()
    if isinstance(context_user, CurrentUser) and context_user.user_id is not None:
        return context_user
    return None


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that resolves user context from API keys."""

    def __init__(self, app, *, api_key: str | None = None) -> None:
        super().__init__(app)

    async def _get_pool(self):
        try:
            db_module = __import__("creator_service.db", fromlist=["get_pool"])
            return await db_module.get_pool()
        except Exception:
            return None

    async def _resolve_member_workspaces(self, user_id: int) -> list[int]:
        pool = await self._get_pool()
        if pool is None:
            return []

        query = (
            "SELECT workspace_id FROM workspace_members WHERE user_id = $1 ORDER BY workspace_id"
        )
        async with pool.acquire() as connection:
            try:
                rows = await connection.fetch(query, user_id)
            except Exception:
                return []

        workspace_ids: list[int] = []
        for row in rows:
            workspace_id = row.get("workspace_id")
            if workspace_id is None:
                continue
            try:
                workspace_ids.append(int(workspace_id))
            except (TypeError, ValueError):
                continue
        return workspace_ids

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.user = CurrentUser()

        # Always allow CORS preflight requests (OPTIONS with Origin header)
        if request.method == "OPTIONS" and "origin" in request.headers:
            return await call_next(request)

        # Always allow public paths
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        if request.url.path == "/docs" and request.app.docs_url is None:
            return await call_next(request)
        if request.url.path == "/redoc" and request.app.redoc_url is None:
            return await call_next(request)
        if request.url.path == "/openapi.json" and request.app.openapi_url is None:
            return await call_next(request)

        # Check header only (never accept keys via query params to avoid log leakage)
        provided = request.headers.get("X-API-Key")
        if not provided:
            # Fall back to Authorization: Bearer <key>
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                provided = auth_header[7:]  # len("Bearer ") == 7

        if not provided:
            return await call_next(request)

        pool = await self._get_pool()
        if pool is None:
            return JSONResponse(
                status_code=503,
                content={"detail": "Service unavailable"},
            )

        async with pool.acquire() as connection:
            user_id = await _resolve_user_id_from_api_key(
                provided, _AsyncpgSessionAdapter(connection)
            )
        if user_id is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "API key is not associated with any user"},
            )

        try:
            user_id_int = int(user_id)
        except (TypeError, ValueError):
            return JSONResponse(
                status_code=401,
                content={"detail": "API key is not associated with any user"},
            )

        member_workspace_ids = await self._resolve_member_workspaces(user_id_int)
        if not member_workspace_ids:
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        workspace_id = member_workspace_ids[0]

        user = CurrentUser(user_id=user_id_int, workspace_id=workspace_id)
        request.state.user = user
        _current_user_ctx.set(user)

        return await call_next(request)
