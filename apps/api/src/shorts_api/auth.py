"""API-key identity middleware and auth helpers."""

from __future__ import annotations

import contextvars
import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun
    from creator_domain.models.project import Project

from creator_service.db import fetch_all, fetch_one
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


@dataclass(frozen=True)
class CurrentUser:
    user_id: int
    workspace_id: int
    workspace_name: str | None = None


class RunAccessContext(NamedTuple):
    user: CurrentUser
    run: PipelineRun


class ProjectAccessContext(NamedTuple):
    user: CurrentUser
    project: Project


def _extract_api_key(request: Request) -> str | None:
    """Extract API key from X-API-Key or Authorization: Bearer header."""
    key = request.headers.get("X-API-Key")
    if key:
        return key
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        return token or None
    return None


class _FetchOneResult:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _AsyncpgSessionAdapter:
    def __init__(self, connection) -> None:
        self._connection = connection

    async def execute(self, query, params: dict[str, object]):
        row = await self._connection.fetchrow("SELECT user_id FROM api_keys WHERE key_hash = $1", params["h"])
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


def _resolve_workspace_id(
    workspace_header: str | None,
    member_workspace_ids: list[int],
) -> int:
    """Resolve the workspace_id from header or default to first workspace.
    
    Args:
        workspace_header: Value of X-Workspace-Id header (or None if not provided)
        member_workspace_ids: List of workspace IDs the user is a member of
        
    Returns:
        The resolved workspace_id
        
    Raises:
        HTTPException(404) if header is invalid or user is not a member
    """
    if workspace_header is None:
        return member_workspace_ids[0]
    
    # Try to parse the header as an integer
    try:
        requested_workspace_id = int(workspace_header)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Not found")
    
    # Verify user is a member of the requested workspace
    if requested_workspace_id not in member_workspace_ids:
        raise HTTPException(status_code=404, detail="Not found")
    
    return requested_workspace_id




class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that resolves user context from API keys."""

    def __init__(self, app) -> None:
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
        request.state.user = None

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

        provided = _extract_api_key(request)

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
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        # Check for X-Workspace-Id header to pin to specific workspace
        workspace_header = request.headers.get("X-Workspace-Id")
        try:
            selected_workspace_id = _resolve_workspace_id(workspace_header, member_workspace_ids)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

        user = CurrentUser(user_id=user_id_int, workspace_id=selected_workspace_id)
        request.state.user = user
        token = _current_user_ctx.set(user)
        try:
            return await call_next(request)
        finally:
            _current_user_ctx.reset(token)


async def get_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if isinstance(user, CurrentUser):
        return user

    context_user = _current_user_ctx.get()
    if isinstance(context_user, CurrentUser):
        return context_user

    api_key = _extract_api_key(request)
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
    
    # Fetch all workspace memberships for this user
    membership_rows = await fetch_all(
        """
        SELECT workspace_id
        FROM workspace_members
        WHERE user_id = $1
        ORDER BY workspace_id ASC
        """,
        user_id,
    )
    if not membership_rows:
        raise HTTPException(status_code=404, detail="Not found")
    
    member_workspace_ids = [row["workspace_id"] for row in membership_rows]
    
    # Check for X-Workspace-Id header to pin to specific workspace
    workspace_header = request.headers.get("X-Workspace-Id")
    selected_workspace_id = _resolve_workspace_id(workspace_header, member_workspace_ids)

    return CurrentUser(user_id=user_id, workspace_id=selected_workspace_id)


async def require_current_user(request: Request) -> CurrentUser:
    return await get_current_user(request)


async def get_authenticated_workspace_id(request: Request) -> int:
    user = await get_current_user(request)
    return user.workspace_id


async def require_workspace_access(
    workspace_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    has_access = await workspace_service.check_access(workspace_id, user.user_id)
    if not has_access:
        raise HTTPException(status_code=404, detail="Not found")

    return user


async def require_api_key_header(request: Request) -> str:
    """Dependency that extracts the API key from the request header.

    Returns the raw API key string. Raises 401 if missing.
    """
    api_key = _extract_api_key(request)
    if not api_key:
        raise HTTPException(status_code=401, detail="API key required")
    return api_key


async def check_run_ownership(
    run_id: int, workspace_id: int, user_id: int
) -> "PipelineRun":
    """Verify run belongs to user's workspace.
    
    Returns the run object if access is verified.
    Raises HTTPException(404) if run not found, project not found, or workspace access denied.
    """
    from creator_service.project_service import project_service
    from creator_service.run_service import run_service

    run = await run_service.get_run(run_id, workspace_id=workspace_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Not found")

    project = await project_service.get_project(run.project_id, workspace_id=workspace_id)
    if project is None or project.workspace_id is None:
        raise HTTPException(status_code=404, detail="Not found")

    has_access = await workspace_service.check_access(project.workspace_id, user_id)
    if not has_access:
        raise HTTPException(status_code=404, detail="Not found")
    
    return run


async def require_run_access(
    run_id: int,
    user: CurrentUser = Depends(require_current_user),
) -> RunAccessContext:
    """Verify the current user owns the workspace that contains the run.

    Returns (user, run) so route handlers can skip re-fetching.
    Raises 404 if run/project not found or workspace mismatch (prevents IDOR).
    """
    run = await check_run_ownership(run_id, user.workspace_id, user.user_id)
    return RunAccessContext(user, run)

async def require_project_access(
    project_id: int,
    user: CurrentUser = Depends(require_current_user),
) -> ProjectAccessContext:
    """Verify the current user owns the workspace that contains the project.

    Returns (user, project) so route handlers can skip re-fetching.
    Raises 404 if project not found or workspace mismatch (prevents IDOR).
    """
    from creator_service.project_service import project_service

    project = await project_service.get_project(project_id, workspace_id=user.workspace_id)
    if project is None or project.workspace_id is None:
        raise HTTPException(status_code=404, detail="Project not found")

    has_access = await workspace_service.check_access(project.workspace_id, user.user_id)
    if not has_access:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectAccessContext(user, project)
