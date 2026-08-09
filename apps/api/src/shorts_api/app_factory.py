import logging
import os
import time

from creator_domain.exceptions import ServiceError
from creator_service.logging_config import setup_json_logging
from creator_service.production_checks import validate_production_config
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware

from shorts_api.auth import ApiKeyMiddleware
from shorts_api.health import register_health_routes
from shorts_api.lifecycle import lifespan, shutdown_state
from shorts_api.routes.admin import router as admin_router
from shorts_api.routes.creator_artifact_download import router as artifact_download_router
from shorts_api.routes.creator_models import router as models_router
from shorts_api.routes.creator_projects import router as projects_router
from shorts_api.routes.creator_run_tasks import router as run_tasks_router
from shorts_api.routes.creator_runs_core import router as runs_core_router
from shorts_api.routes.creator_runs_lifecycle import router as runs_lifecycle_router
from shorts_api.routes.creator_runs_scene_assets import router as runs_scene_assets_router
from shorts_api.routes.creator_runs_storyboard import router as runs_storyboard_router
from shorts_api.routes.creator_runs_visuals import router as runs_visuals_router
from shorts_api.routes.creator_script import router as script_router
from shorts_api.routes.creator_script import run_script_router
from shorts_api.routes.creator_settings import router as settings_router
from shorts_api.routes.creator_usage import router as usage_router
from shorts_api.routes.creator_users import router as users_router
from shorts_api.routes.creator_visual_plan import router as visual_plan_router
from shorts_api.routes.creator_workspaces import router as workspaces_router

setup_json_logging(service_name="api", level="INFO")
logger = logging.getLogger(__name__)
validate_production_config()


runs_router = APIRouter()
runs_router.include_router(runs_core_router)
runs_router.include_router(runs_visuals_router)
runs_router.include_router(runs_scene_assets_router)
runs_router.include_router(runs_storyboard_router)
runs_router.include_router(runs_lifecycle_router)


def create_app() -> FastAPI:
    environment = os.getenv("ENVIRONMENT", "development").strip().lower()
    production_hardened = environment == "production"

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

    async def request_logging_middleware(request: Request, call_next):
        shutdown_state.inflight_requests += 1
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            shutdown_state.inflight_requests = max(0, shutdown_state.inflight_requests - 1)
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "%s %s %d %.1fms",
                request.method,
                request.url.path,
                status_code,
                elapsed_ms,
            )

    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        if production_hardened:
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    async def shutdown_guard_middleware(request: Request, call_next):
        if "PYTEST_CURRENT_TEST" in os.environ:
            return await call_next(request)
        if shutdown_state.is_shutting_down and request.url.path != "/healthz":
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"detail": "Server shutting down"},
            )
        return await call_next(request)

    # add_middleware inserts at the front of the stack, so the LAST call is outermost.
    # Order (outermost → innermost at runtime):
    #   CORS → request_logging → security_headers → shutdown_guard → [Telemetry] → ApiKey
    # CORS must be outermost so auth failures (401/403/404/503) still get CORS headers (#600).
    app.add_middleware(BaseHTTPMiddleware, dispatch=request_logging_middleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=security_headers_middleware)
    app.add_middleware(BaseHTTPMiddleware, dispatch=shutdown_guard_middleware)
    app.add_middleware(ApiKeyMiddleware)
    if os.getenv("OTEL_ENABLED", "").lower() in ("true", "1", "yes", "on"):
        from shorts_api.middleware.telemetry import TelemetryMiddleware

        app.add_middleware(TelemetryMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        """Central mapping from typed service exceptions to HTTP responses."""
        return JSONResponse(
            status_code=exc.http_status_code,
            content={"detail": exc.detail},
        )

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
    app.include_router(run_tasks_router, prefix="/api/creator")
    app.include_router(artifact_download_router, prefix="/api/creator")
    app.include_router(script_router, prefix="/api/creator")
    app.include_router(run_script_router, prefix="/api/creator")
    app.include_router(visual_plan_router, prefix="/api/creator")
    app.include_router(settings_router, prefix="/api/creator")
    app.include_router(usage_router, prefix="/api/creator")
    app.include_router(workspaces_router, prefix="/api/creator")
    app.include_router(users_router, prefix="/api/creator")
    app.include_router(admin_router, prefix="/api/admin")
    register_health_routes(app)
    return app
