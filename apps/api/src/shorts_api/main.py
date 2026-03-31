"""FastAPI entrypoint for shorts_api."""
import logging
import os
import time

from creator_service.model_health_service import ModelHealthService
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from creator_service.logging_config import setup_json_logging
from shorts_api.routes.creator_models import router as models_router
from shorts_api.routes.creator_projects import router as projects_router
from shorts_api.routes.creator_runs import router as runs_router
from shorts_api.routes.creator_script import router as script_router, run_script_router
from shorts_api.routes.creator_visual_plan import router as visual_plan_router

# Configure structured JSON logging
setup_json_logging(service_name="api", level="INFO")
logger = logging.getLogger(__name__)

app = FastAPI(title="short-form-pipeline API")

cors_origins_env = os.getenv("CORS_ORIGINS")
cors_origins = [
    origin.strip() for origin in cors_origins_env.split(",") if origin.strip()
] if cors_origins_env else ["http://localhost:5173"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



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
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

app.include_router(models_router, prefix="/api/creator")
app.include_router(projects_router, prefix="/api/creator")
app.include_router(runs_router, prefix="/api/creator")
app.include_router(script_router, prefix="/api/creator")
app.include_router(run_script_router, prefix="/api/creator")
app.include_router(visual_plan_router, prefix="/api/creator")


@app.get("/health")
async def health() -> dict[str, object]:
    results = await model_health.check_all()
    all_healthy = all(r.status.value == "healthy" for r in results)
    return {
        "status": "ok" if all_healthy else "degraded",
        "models": {
            r.model_name: {
                "status": r.status.value,
                "endpoint": r.endpoint,
                "response_time_ms": r.response_time_ms,
                "error": r.error,
            }
            for r in results
        },
    }


app.mount(
    "/artifacts",
    StaticFiles(directory=os.getenv("ARTIFACT_ROOT", "data/artifacts"), check_dir=False),
    name="artifacts",
)
