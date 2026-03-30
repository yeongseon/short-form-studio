"""Routes for creator model management."""
# pyright: reportMissingImports=false

import logging
import os
import sys

from fastapi import APIRouter, HTTPException, Query

# Add packages to path for imports
_PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "../../../../..", "packages")
sys.path.insert(0, _PACKAGES_DIR)
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-service"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-provider"))

try:
    from creator_provider.registry import ProviderRegistry
    from creator_service.model_catalog_service import ModelCatalogService
    from creator_service.model_health_service import ModelHealthService
except ImportError:
    from model_catalog_service import ModelCatalogService
    from model_health_service import ModelHealthService
    from registry import ProviderRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

VALID_CATEGORIES = {"script", "image", "tts", "stt"}
model_catalog_service = ModelCatalogService(
    registry=ProviderRegistry.create_default(),
    health_service=ModelHealthService(),
)


@router.get("")
async def list_models(category: str | None = Query(default=None)) -> dict[str, list[dict[str, object]]]:
    """List available creator models by category."""
    if category is not None and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")

    return await model_catalog_service.list_models(category=category)


@router.get("/status")
async def get_model_status() -> dict[str, object]:
    """Return provider-level status and GPU lock state."""
    logger.info("Model status check requested")
    status = await model_catalog_service.get_status()
    logger.info("Model status check completed")
    return status
