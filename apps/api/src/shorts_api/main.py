# pyright: reportMissingImports=false

import os

from creator_service.artifact_download_service import read_artifact_bytes
from creator_service.db import get_pool
from redis.asyncio import Redis

from shorts_api.app_factory import create_app
from shorts_api.app_factory import admin_router  # noqa: E402, F401
from shorts_api.app_factory import artifact_download_router  # noqa: E402, F401
from shorts_api.app_factory import models_router  # noqa: E402, F401
from shorts_api.app_factory import projects_router  # noqa: E402, F401
from shorts_api.app_factory import run_script_router  # noqa: E402, F401
from shorts_api.app_factory import run_tasks_router  # noqa: E402, F401
from shorts_api.app_factory import runs_core_router  # noqa: E402, F401
from shorts_api.app_factory import runs_lifecycle_router  # noqa: E402, F401
from shorts_api.app_factory import runs_router  # noqa: E402, F401
from shorts_api.app_factory import runs_scene_assets_router  # noqa: E402, F401
from shorts_api.app_factory import runs_storyboard_router  # noqa: E402, F401
from shorts_api.app_factory import runs_visuals_router  # noqa: E402, F401
from shorts_api.app_factory import script_router  # noqa: E402, F401
from shorts_api.app_factory import settings_router  # noqa: E402, F401
from shorts_api.app_factory import usage_router  # noqa: E402, F401
from shorts_api.app_factory import users_router  # noqa: E402, F401
from shorts_api.app_factory import visual_plan_router  # noqa: E402, F401
from shorts_api.app_factory import workspaces_router  # noqa: E402, F401
from shorts_api.health import model_health  # noqa: E402, F401

_is_production = os.getenv("ENVIRONMENT", "development").strip().lower() == "production"

app = create_app()
