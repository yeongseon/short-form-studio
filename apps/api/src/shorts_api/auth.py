"""API-key identity middleware and auth helpers."""

from __future__ import annotations

import contextvars
import hashlib
import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun
    from creator_domain.models.project import Project

from creator_service.db import fetch_one
from creator_service.workspace_service import workspace_service
from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

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
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    result = await db_session.execute(
        text("SELECT user_id FROM api_keys WHERE key_hash = :h AND revoked_at IS NULL"),
        {"h": key_hash},
    )
    row = result.fetchone()
    return row[0] if row else None


_ADMIN_PATH_PREFIX = "/api/admin"


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that resolves user context from API keys."""

    def __init__(self, app, *, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = os.getenv("API_KEY") if api_key is None else api_key

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

        if request.method == "OPTIONS" and "origin" in request.headers:
            return await call_next(request)
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)
        if request.url.path == "/docs" and request.app.docs_url is None:
            return await call_next(request)
        if request.url.path == "/redoc" and request.app.redoc_url is None:
            return await call_next(request)
        if request.url.path == "/openapi.json" and request.app.openapi_url is None:
            return await call_next(request)

        if request.url.path.startswith(_ADMIN_PATH_PREFIX):
            return await call_next(request)

        # Docs paths go through normal auth when API_KEY is set
        # (they were removed from _PUBLIC_PATHS so they're not auto-allowed)

        # Check header only (never accept keys via query params to avoid log leakage)
        provided = request.headers.get("X-API-Key")
        if not provided:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                provided = auth_header[7:]

        if not provided:
            if request.url.path.startswith("/api/creator"):
                return JSONResponse(status_code=401, content={"detail": "API key required"})
            return await call_next(request)

        pool = await self._get_pool()
        if pool is None:
            return JSONResponse(status_code=503, content={"detail": "Service unavailable"})

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

        user = CurrentUser(user_id=user_id_int, workspace_id=member_workspace_ids[0])
        request.state.user = user
        token = _current_user_ctx.set(user)
        try:
            return await call_next(request)
        finally:
            _current_user_ctx.reset(token)


async def get_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if isinstance(user, CurrentUser) and user.user_id is not None:
        return user

    context_user = _current_user_ctx.get()
    if isinstance(context_user, CurrentUser) and context_user.user_id is not None:
        return context_user

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
    if membership_row is None:
        raise HTTPException(status_code=403, detail="No workspace membership")

    return CurrentUser(user_id=user_id, workspace_id=membership_row["workspace_id"])


async def require_current_user(request: Request) -> CurrentUser:
    return await get_current_user(request)


async def get_authenticated_workspace_id(request: Request) -> int | None:
    user = await get_current_user(request)
    return user.workspace_id


async def require_workspace_access(
    workspace_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if user.user_id is None:
        raise HTTPException(status_code=401, detail="Invalid user context")

    has_access = await workspace_service.check_access(workspace_id, user.user_id)
    if not has_access:
        raise HTTPException(status_code=404, detail="Not found")

    return user


async def get_api_key(request: Request) -> str:
    """Dependency that extracts and validates the API key from the request.

    Returns the raw API key string. Raises 401 if missing/invalid.
    """
    api_key = (
        request.headers.get("X-API-Key")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    return api_key


async def require_run_access(
    run_id: int,
    user: CurrentUser = Depends(require_current_user),
) -> tuple[CurrentUser, PipelineRun]:
    """Verify the current user owns the workspace that contains the run.

    Returns (user, run) so route handlers can skip re-fetching.
    Raises 404 if run/project not found or workspace mismatch (prevents IDOR).
    """
    from creator_service.project_service import project_service
    from creator_service.run_service import run_service

    if user.user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    project = await project_service.get_project(run.project_id)
    if project is None or project.workspace_id is None:
        raise HTTPException(status_code=404, detail="Run not found")

    has_access = await workspace_service.check_access(project.workspace_id, user.user_id)
    if not has_access:
        raise HTTPException(status_code=404, detail="Run not found")
    return user, run


async def require_project_access(
    project_id: int,
    user: CurrentUser = Depends(require_current_user),
) -> tuple[CurrentUser, Project]:
    """Verify the current user owns the workspace that contains the project.

    Returns (user, project) so route handlers can skip re-fetching.
    Raises 404 if project not found or workspace mismatch (prevents IDOR).
    """
    from creator_service.project_service import project_service

    if user.user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    project = await project_service.get_project(project_id)
    if project is None or project.workspace_id is None:
        raise HTTPException(status_code=404, detail="Project not found")

    has_access = await workspace_service.check_access(project.workspace_id, user.user_id)
    if not has_access:
        raise HTTPException(status_code=404, detail="Project not found")

    return user, project
