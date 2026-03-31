"""FastAPI entrypoint for shorts_api."""
import os
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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

app.include_router(models_router, prefix="/api/creator")
app.include_router(projects_router, prefix="/api/creator")
app.include_router(runs_router, prefix="/api/creator")
app.include_router(script_router, prefix="/api/creator")
app.include_router(run_script_router, prefix="/api/creator")
app.include_router(visual_plan_router, prefix="/api/creator")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount(
    "/artifacts",
    StaticFiles(directory=os.getenv("ARTIFACT_ROOT", "data/artifacts"), check_dir=False),
    name="artifacts",
)
