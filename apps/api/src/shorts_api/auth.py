"""Optional API-key authentication middleware.

When the ``API_KEY`` environment variable is set, every request (except health
checks) must carry a matching key via the ``X-API-Key`` header or the standard
``Authorization: Bearer <key>`` header.  When the variable is unset the
middleware is a transparent pass-through so local development stays frictionless.
"""

import contextvars
import hmac
import json
import logging
import os
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
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
    workspace_id: int | None = None
    workspace_name: str | None = None


async def get_current_user(request: Request) -> CurrentUser:
    user = getattr(request.state, "user", None)
    if isinstance(user, CurrentUser):
        return user

    context_user = _current_user_ctx.get()
    if isinstance(context_user, CurrentUser):
        return context_user

    return CurrentUser()


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces an optional API key."""

    def __init__(self, app, *, api_key: str | None = None) -> None:
        super().__init__(app)
        self._api_key = api_key or os.getenv("API_KEY")

    @staticmethod
    def _parse_workspace_map() -> dict[str, int]:
        raw = os.getenv("API_KEY_WORKSPACE_MAP", "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid API_KEY_WORKSPACE_MAP JSON; ignoring configured map")
            return {}
        if not isinstance(parsed, dict):
            logger.warning("API_KEY_WORKSPACE_MAP must be a JSON object; ignoring configured map")
            return {}

        mapping: dict[str, int] = {}
        for key, value in parsed.items():
            if not isinstance(key, str):
                continue
            try:
                mapping[key] = int(value)
            except (TypeError, ValueError):
                logger.warning("Ignoring API_KEY_WORKSPACE_MAP entry with non-integer workspace_id")
        return mapping

    async def _resolve_workspace_from_membership(self, api_key_value: str) -> int | None:
        try:
            db_module = __import__("creator_service.db", fromlist=["get_pool"])
            pool = await db_module.get_pool()
        except Exception:
            return None

        candidate_queries = (
            "SELECT workspace_id FROM workspace_members WHERE user_id::text = $1 ORDER BY workspace_id LIMIT 1",
        )
        async with pool.acquire() as connection:
            for query in candidate_queries:
                try:
                    row = await connection.fetchrow(query, api_key_value)
                except Exception:
                    continue
                if row is not None and row.get("workspace_id") is not None:
                    try:
                        return int(row["workspace_id"])
                    except (TypeError, ValueError):
                        continue
        return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.user = CurrentUser()

        # Skip auth when no key is configured (local dev)
        workspace_map = self._parse_workspace_map()
        valid_keys = set(workspace_map.keys())
        if self._api_key:
            valid_keys.add(self._api_key)

        if not valid_keys:
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

        if not provided or not any(hmac.compare_digest(provided, key) for key in valid_keys):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        workspace_id = workspace_map.get(provided)
        if workspace_id is None:
            workspace_id = await self._resolve_workspace_from_membership(provided)

        if workspace_id is None:
            workspace_header = request.headers.get("X-Workspace-Id")
            if workspace_header is not None:
                try:
                    workspace_id = int(workspace_header)
                except ValueError:
                    return JSONResponse(
                        status_code=400, content={"detail": "Invalid X-Workspace-Id header"}
                    )
                logger.warning(
                    "Falling back to X-Workspace-Id because workspace mapping lookup is unavailable; this behavior is deprecated"
                )

        user = CurrentUser(workspace_id=workspace_id)
        request.state.user = user
        _current_user_ctx.set(user)

        return await call_next(request)
