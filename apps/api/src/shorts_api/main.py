# pyright: reportMissingImports=false

"""FastAPI entrypoint for shorts_api."""

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from creator_service.db import close_pool
from creator_service.logging_config import setup_json_logging
from creator_service.model_health_service import ModelHealthService, ModelStatus
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import FileResponse

from shorts_api.auth import ApiKeyMiddleware
from shorts_api.routes.creator_artifact_download import router as artifact_download_router
from shorts_api.routes.creator_models import router as models_router
from shorts_api.routes.creator_projects import router as projects_router
from shorts_api.routes.creator_runs_core import router as runs_core_router
from shorts_api.routes.creator_runs_lifecycle import router as runs_lifecycle_router
from shorts_api.routes.creator_runs_scene_assets import router as runs_scene_assets_router
from shorts_api.routes.creator_runs_storyboard import router as runs_storyboard_router
from shorts_api.routes.creator_runs_visuals import router as runs_visuals_router
from shorts_api.routes.creator_script import router as script_router
from shorts_api.routes.creator_script import run_script_router
from shorts_api.routes.creator_settings import router as settings_router
from shorts_api.routes.creator_visual_plan import router as visual_plan_router
from shorts_api.routes.creator_workspaces import router as workspaces_router

# Combined runs router for backward compatibility (used by tests)
runs_router = APIRouter()
runs_router.include_router(runs_core_router)
runs_router.include_router(runs_visuals_router)
runs_router.include_router(runs_scene_assets_router)
runs_router.include_router(runs_storyboard_router)
runs_router.include_router(runs_lifecycle_router)

# Configure structured JSON logging
setup_json_logging(service_name="api", level="INFO")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_pool()


environment = os.getenv("ENVIRONMENT", "development").strip().lower()
production_hardened = environment == "production" and bool(os.getenv("API_KEY"))

app = FastAPI(
    title="short-form-studio API",
    lifespan=lifespan,
    docs_url=None if production_hardened else "/docs",
    redoc_url=None if production_hardened else "/redoc",
    openapi_url=None if production_hardened else "/openapi.json",
)

cors_origins_env = os.getenv("CORS_ORIGINS")
cors_origins = (
    [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]
    if cors_origins_env
    else ["http://localhost:5174"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiKeyMiddleware)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            status_code,
            elapsed_ms,
        )


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


model_health = ModelHealthService()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, _exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


app.include_router(models_router, prefix="/api/creator")
app.include_router(projects_router, prefix="/api/creator")
app.include_router(runs_core_router, prefix="/api/creator")
app.include_router(runs_visuals_router, prefix="/api/creator")
app.include_router(runs_scene_assets_router, prefix="/api/creator")
app.include_router(runs_storyboard_router, prefix="/api/creator")
app.include_router(runs_lifecycle_router, prefix="/api/creator")
app.include_router(artifact_download_router, prefix="/api/creator")
app.include_router(script_router, prefix="/api/creator")
app.include_router(run_script_router, prefix="/api/creator")
app.include_router(visual_plan_router, prefix="/api/creator")
app.include_router(settings_router, prefix="/api/creator")
app.include_router(workspaces_router, prefix="/api/creator")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Lightweight liveness probe — no auth required."""
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict[str, object]:
    """Detailed model health — endpoint URLs and error details are stripped.

    Only returns model name, status, and response time.
    """
    results = await model_health.check_all()
    # Only consider providers with a definitive status (healthy/unhealthy/configured)
    # for overall readiness.  UNKNOWN means "not configured" and should not
    # degrade a correctly-configured deployment.
    definitive = [r for r in results if r.status not in (ModelStatus.UNKNOWN,)]
    all_healthy = len(definitive) > 0 and all(
        r.status in (ModelStatus.HEALTHY, ModelStatus.CONFIGURED) for r in definitive
    )
    return {
        "status": "ok" if all_healthy else "degraded",
        "models": {
            r.model_name: {
                "status": r.status.value,
                "response_time_ms": r.response_time_ms,
            }
            for r in results
        },
    }


@app.get("/artifacts/{artifact_path:path}", deprecated=True)
async def serve_artifact(artifact_path: str) -> FileResponse:
    """Backward-compatible artifact serving — DEPRECATED.

    In production (API_KEY set), this returns 410 Gone to enforce migration
    to the access-controlled endpoint. In dev mode, it serves files directly
    for convenience but still emits deprecation headers.

    Clients MUST migrate to:
    ``GET /api/creator/runs/{run_id}/artifacts/{artifact_id}/download``
    which enforces expiration and ownership.
    """
    # Production: reject outright — legacy route bypasses access control
    if os.getenv("API_KEY"):
        raise HTTPException(
            status_code=410,
            detail=(
                "This endpoint is removed in production. "
                "Use GET /api/creator/runs/{run_id}/artifacts/{artifact_id}/download instead."
            ),
        )

    # Dev mode: serve with deprecation warnings
    artifact_root = os.path.realpath(os.getenv("ARTIFACT_ROOT", "data/artifacts"))
    resolved = os.path.realpath(os.path.join(artifact_root, artifact_path))
    if os.path.commonpath([artifact_root, resolved]) != artifact_root:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not os.path.isfile(resolved):
        raise HTTPException(status_code=404, detail="Artifact not found")
    response = FileResponse(resolved)
    response.headers["Deprecation"] = "true"
    response.headers["Link"] = (
        '</api/creator/runs/{run_id}/artifacts/{artifact_id}/download>; rel="successor-version"'
    )
    return response
