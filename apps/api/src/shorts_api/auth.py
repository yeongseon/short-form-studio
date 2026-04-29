from hashlib import sha256
from dataclasses import dataclass

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/healthz"})


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int | None
    workspace_id: int | None


def _resolve_authenticated_user(request: Request) -> AuthenticatedUser:
    existing = getattr(request.state, "user", None)
    if isinstance(existing, AuthenticatedUser):
        return existing

    user_id = getattr(existing, "user_id", None) if existing is not None else None
    workspace_id = getattr(existing, "workspace_id", None) if existing is not None else None
    return AuthenticatedUser(
        user_id=int(user_id) if isinstance(user_id, int) else None,
        workspace_id=int(workspace_id) if isinstance(workspace_id, int) else None,
    )


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, api_key: str | None = None) -> None:
        super().__init__(app)
        _ = api_key

    @staticmethod
    def _extract_api_key(request: Request) -> str | None:
        provided = request.headers.get("X-API-Key")
        if provided:
            return provided
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return None

    async def _resolve_user_from_api_key(self, api_key: str) -> AuthenticatedUser:
        fetch_one = __import__("creator_service.db", fromlist=["fetch_one"]).fetch_one

        api_key_hash = sha256(api_key.encode("utf-8")).hexdigest()
        user = await fetch_one(
            "SELECT user_id FROM api_keys WHERE key_hash = $1",
            api_key_hash,
        )
        if user is None:
            return AuthenticatedUser(user_id=None, workspace_id=None)

        user_id = int(user["user_id"])
        membership = await fetch_one(
            """
            SELECT workspace_id
            FROM workspace_members
            WHERE user_id = $1
            ORDER BY workspace_id ASC
            LIMIT 1
            """,
            user_id,
        )
        workspace_id = int(membership["workspace_id"]) if membership is not None else None
        return AuthenticatedUser(user_id=user_id, workspace_id=workspace_id)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Always allow CORS preflight requests (OPTIONS with Origin header)
        if request.method == "OPTIONS" and "origin" in request.headers:
            return await call_next(request)

        # Always allow public paths
        if request.url.path in _PUBLIC_PATHS:
            request.state.user = _resolve_authenticated_user(request)
            return await call_next(request)

        # Docs paths go through normal auth when API_KEY is set
        # (they were removed from _PUBLIC_PATHS so they're not auto-allowed)

        # Check header only (never accept keys via query params to avoid log leakage)
        provided = self._extract_api_key(request)
        if not provided:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )

        try:
            request.state.user = await self._resolve_user_from_api_key(provided)
        except Exception:
            request.state.user = AuthenticatedUser(user_id=None, workspace_id=None)
        if request.state.user.user_id is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)


async def get_api_key(request: Request) -> str:
    provided = ApiKeyMiddleware._extract_api_key(request)
    if not provided:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

    user = _resolve_authenticated_user(request)
    if user.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )

    return provided
