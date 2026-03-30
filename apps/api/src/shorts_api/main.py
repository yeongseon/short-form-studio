"""FastAPI entrypoint for shorts_api."""

import logging
import os
import sys

from fastapi import FastAPI

# Add packages to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../..", "packages"))

from creator_service.logging_config import setup_json_logging
from shorts_api.routes import creator_models

# Configure structured JSON logging
setup_json_logging(service_name="api", level="INFO")
logger = logging.getLogger(__name__)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
