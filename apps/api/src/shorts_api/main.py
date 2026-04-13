"""FastAPI entrypoint for shorts_api."""
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from creator_service.db import close_pool
from creator_service.logging_config import setup_json_logging
from creator_service.model_health_service import ModelHealthService
from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from shorts_api.auth import ApiKeyMiddleware
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


app = FastAPI(title="short-form-studio API", lifespan=lifespan)

cors_origins_env = os.getenv("CORS_ORIGINS")
cors_origins = [
    origin.strip() for origin in cors_origins_env.split(",") if origin.strip()
] if cors_origins_env else ["http://localhost:5174"]

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
app.include_router(script_router, prefix="/api/creator")
app.include_router(run_script_router, prefix="/api/creator")
app.include_router(visual_plan_router, prefix="/api/creator")
app.include_router(settings_router, prefix="/api/creator")


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
    all_healthy = all(r.status.value == "healthy" for r in results)
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


app.mount(
    "/artifacts",
    StaticFiles(directory=os.getenv("ARTIFACT_ROOT", "data/artifacts"), check_dir=False),
    name="artifacts",
)
