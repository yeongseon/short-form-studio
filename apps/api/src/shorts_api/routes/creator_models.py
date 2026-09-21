"""Routes for creator model management."""

import dataclasses
import logging

from creator_provider.api_keys import list_configured_providers
from creator_provider.registry import get_default_registry
from creator_service.model_catalog_service import ModelCatalogService
from creator_service.model_health_service import ModelHealthService
from creator_service.provider_config_view import resolve_provider_config_view
from fastapi import APIRouter, Depends, HTTPException, Query

from shorts_api.auth import CurrentUser, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])

VALID_CATEGORIES = {"script", "image", "tts", "stt"}
_health_service = ModelHealthService()
model_catalog_service = ModelCatalogService(
    registry=get_default_registry(),
    health_service=_health_service,
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


@router.get("/provider-config")
async def get_provider_config(
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, object]:
    """Return the first-run provider-configuration view (credential-free, endpoint-free)."""
    # No resource-scoped access helper: provider-config is global infrastructure metadata,
    # and the resolver guarantees no secret value or internal endpoint crosses the boundary.
    view = await resolve_provider_config_view(
        registry=get_default_registry(),
        health_service=_health_service,
        configured_providers=list_configured_providers(),
    )
    return dataclasses.asdict(view)
