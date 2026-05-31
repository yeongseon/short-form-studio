"""Routes for creator model management."""

import logging

from creator_provider.registry import get_default_registry
from creator_service.model_catalog_service import ModelCatalogService
from creator_service.model_health_service import ModelHealthService
from fastapi import APIRouter, Depends, HTTPException, Query

from shorts_api.auth import CurrentUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

VALID_CATEGORIES = {"script", "image", "tts", "stt"}
model_catalog_service = ModelCatalogService(
    registry=get_default_registry(),
    health_service=ModelHealthService(),
)


@router.get("")
async def list_models(
    user: CurrentUser = Depends(get_current_user),
    category: str | None = Query(default=None),
) -> dict[str, list[dict[str, object]]]:
    """List available creator models by category."""
    # No resource-scoped access helper: this endpoint only exposes global model catalog metadata.
    if category is not None and category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")

    return await model_catalog_service.list_models(category=category)


@router.get("/status")
async def get_model_status(user: CurrentUser = Depends(get_current_user)) -> dict[str, object]:
    """Return provider-level status and GPU lock state."""
    # No resource-scoped access helper: status is provider-level infrastructure metadata.
    logger.info("Model status check requested")
    status = await model_catalog_service.get_status()
    logger.info("Model status check completed")
    return status
