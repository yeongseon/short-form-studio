# pyright: reportMissingImports=false

"""FastAPI entrypoint for shorts_api."""

import asyncio
import contextlib
import logging
import mimetypes
import os
import resource
import signal
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from creator_domain.sanitize import UnsafePathComponent, sanitize_path_component
from creator_service.artifact_download_service import read_artifact_bytes
from creator_service.db import close_pool, get_pool
from creator_service.logging_config import setup_json_logging
from creator_service.model_health_service import ModelHealthService, ModelStatus
from creator_service.production_checks import validate_production_config
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette import status
from starlette.responses import FileResponse, Response

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
from shorts_api.routes.creator_users import router as users_router

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

validate_production_config()


@dataclass
class ShutdownState:
    is_shutting_down: bool = False
    inflight_requests: int = 0


shutdown_state = ShutdownState()


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default
    if parsed <= 0:
        logger.warning("Non-positive %s=%r; using default %d", name, raw, default)
        return default
    return parsed


MAX_MEMORY_MB = _parse_int_env("MAX_MEMORY_MB", 1024)
MAX_CPU_PERCENT = _parse_int_env("MAX_CPU_PERCENT", 80)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


def _apply_resource_limits() -> None:
    memory_limit_bytes = MAX_MEMORY_MB * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit_bytes, memory_limit_bytes))
    except (OSError, ValueError):
        logger.error(
            "Failed to set RLIMIT_AS to %d bytes during startup",
            memory_limit_bytes,
            exc_info=True,
        )
        raise


def _cpu_usage_percent(
    previous_cpu_seconds: float, previous_wall_seconds: float
) -> tuple[float, float, float]:
    current_cpu_seconds = (
        resource.getrusage(resource.RUSAGE_SELF).ru_utime
        + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    )
    current_wall_seconds = time.monotonic()
    cpu_delta = max(0.0, current_cpu_seconds - previous_cpu_seconds)
    wall_delta = max(1e-6, current_wall_seconds - previous_wall_seconds)
    cpu_percent = (cpu_delta / wall_delta) * 100.0
    return cpu_percent, current_cpu_seconds, current_wall_seconds


async def _monitor_cpu_limit() -> None:
    cpu_seconds = (
        resource.getrusage(resource.RUSAGE_SELF).ru_utime
        + resource.getrusage(resource.RUSAGE_SELF).ru_stime
    )
    wall_seconds = time.monotonic()
    while True:
        await asyncio.sleep(2.0)
        cpu_percent, cpu_seconds, wall_seconds = _cpu_usage_percent(cpu_seconds, wall_seconds)
        if cpu_percent > float(MAX_CPU_PERCENT):
            logger.error(
                "CPU usage %.1f%% exceeded MAX_CPU_PERCENT=%d; enabling shutdown guard",
                cpu_percent,
                MAX_CPU_PERCENT,
            )
            _mark_shutdown()
            os._exit(1)


def _mark_shutdown() -> None:
    if shutdown_state.is_shutting_down:
        return
    shutdown_state.is_shutting_down = True
    logger.info("Graceful shutdown initiated; draining in-flight requests")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _apply_resource_limits()
    logger.info(
        "Resource limits configured: MAX_MEMORY_MB=%d, MAX_CPU_PERCENT=%d",
        MAX_MEMORY_MB,
        MAX_CPU_PERCENT,
    )
    cpu_monitor_task = asyncio.create_task(_monitor_cpu_limit())

    signal_handlers_registered = False
    loop: asyncio.AbstractEventLoop | None = None
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _mark_shutdown)
        loop.add_signal_handler(signal.SIGINT, _mark_shutdown)
        signal_handlers_registered = True
        logger.info("Registered SIGTERM/SIGINT handlers for graceful shutdown")
    except (NotImplementedError, RuntimeError):
        logger.warning("Signal handlers are unavailable in this runtime")

    yield
    _mark_shutdown()
    cpu_monitor_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cpu_monitor_task
    if signal_handlers_registered and loop is not None:
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.remove_signal_handler(signal.SIGTERM)
            loop.remove_signal_handler(signal.SIGINT)
    await close_pool()


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


@app.middleware("http")
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


@app.middleware("http")
async def shutdown_guard_middleware(request: Request, call_next):
    if shutdown_state.is_shutting_down and request.url.path != "/healthz":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Server shutting down"},
        )
    return await call_next(request)


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
app.include_router(users_router, prefix="/api/creator")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Lightweight liveness probe — no auth required."""
    return {"status": "ok"}


@app.get("/health")
async def health() -> dict[str, object]:
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment in {"production", "staging"}:
        db_ok = False
        redis_ok = False
        db_error: str | None = None
        redis_error: str | None = None

        try:
            pool = await get_pool()
            value = await pool.fetchval("SELECT 1")
            db_ok = value == 1
            if not db_ok:
                db_error = "Unexpected DB ping response"
        except Exception as exc:
            db_error = str(exc)

        redis_client = Redis.from_url(REDIS_URL)
        try:
            redis_pong = await redis_client.ping()
            redis_ok = bool(redis_pong)
            if not redis_ok:
                redis_error = "Unexpected Redis ping response"
        except Exception as exc:
            redis_error = str(exc)
        finally:
            await redis_client.aclose()

        overall_ok = db_ok and redis_ok and not shutdown_state.is_shutting_down
        response_payload = {
            "status": "ok" if overall_ok else "unavailable",
            "checks": {
                "database": {"status": "ok" if db_ok else "down"},
                "redis": {"status": "ok" if redis_ok else "down"},
            },
            "shutdown": shutdown_state.is_shutting_down,
            "resource_limits": {
                "max_memory_mb": MAX_MEMORY_MB,
                "max_cpu_percent": MAX_CPU_PERCENT,
            },
        }
        if db_error:
            response_payload["checks"]["database"]["error"] = db_error
        if redis_error:
            response_payload["checks"]["redis"]["error"] = redis_error

        if not overall_ok:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=response_payload,
            )
        return response_payload

    results = await model_health.check_all()
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
async def serve_artifact(artifact_path: str):
    path_components = artifact_path.split("/")
    if not artifact_path or any(component in {"", ".", ".."} for component in path_components):
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    try:
        safe_components = [
            sanitize_path_component(component, label=f"artifact_path[{index}]")
            for index, component in enumerate(path_components)
        ]
    except UnsafePathComponent as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage_key = "/".join(safe_components)
    try:
        content = read_artifact_bytes(storage_key)
        media_type, _ = mimetypes.guess_type(storage_key)
        return Response(content=content, media_type=media_type or "application/octet-stream")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Artifact read failed") from exc


@app.get("/api/artifacts/files/{path:path}")
async def serve_local_artifact_file(path: str) -> Response:
    path_components = path.split("/")
    if (
        not path
        or path.startswith("/")
        or any(component in {"", ".", ".."} for component in path_components)
    ):
        raise HTTPException(status_code=400, detail="Invalid artifact path")

    try:
        safe_components = [
            sanitize_path_component(component, label=f"path[{index}]")
            for index, component in enumerate(path_components)
        ]
    except UnsafePathComponent as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage_key = "/".join(safe_components)

    try:
        content = read_artifact_bytes(storage_key)
        media_type, _ = mimetypes.guess_type(storage_key)
        return Response(content=content, media_type=media_type or "application/octet-stream")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Artifact read failed") from exc
