"""FastAPI entrypoint for shorts_api."""
# pyright: reportMissingImports=false

import logging
import os
import sys

from fastapi import FastAPI

# Add packages to path for imports
_PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "../../../..", "packages")
sys.path.insert(0, _PACKAGES_DIR)
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-service"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-provider"))

try:
    from creator_service.logging_config import setup_json_logging
except ImportError:
    from logging_config import setup_json_logging
from shorts_api.routes.creator_models import router as models_router

# Configure structured JSON logging
setup_json_logging(service_name="api", level="INFO")
logger = logging.getLogger(__name__)

app = FastAPI(title="short-form-pipeline API")
app.include_router(models_router, prefix="/api/creator")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
