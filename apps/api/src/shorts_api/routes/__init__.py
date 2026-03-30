"""Route modules for creator API."""

from fastapi import APIRouter

from . import (
    creator_assets,
    creator_audio,
    creator_models,
    creator_projects,
    creator_render,
    creator_runs,
    creator_script,
    creator_visual_plan,
)

creator_router = APIRouter()

# Include all creator sub-routers
creator_router.include_router(creator_projects.router)
creator_router.include_router(creator_runs.router)
creator_router.include_router(creator_script.router)
creator_router.include_router(creator_visual_plan.router)
creator_router.include_router(creator_assets.router)
creator_router.include_router(creator_audio.router)
creator_router.include_router(creator_render.router)
creator_router.include_router(creator_models.router)

__all__ = ["creator_router"]
