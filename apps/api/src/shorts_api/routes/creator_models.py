"""Routes for creator model management."""

import logging
import sys
import os
from fastapi import APIRouter

# Add packages to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../..", "packages"))

from creator_service.model_health_service import ModelHealthService, ModelHealthResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


@router.get("/status")
async def get_model_status() -> dict:
    """Get health status of all model serving containers.
    
    Returns:
        Dictionary containing list of model health results.
    """
    logger.info("Model status check requested")
    
    health_service = ModelHealthService()
    results = await health_service.check_all()
    
    # Convert enum values to strings for JSON serialization
    results_dict = [
        {
            "model_name": result.model_name,
            "endpoint": result.endpoint,
            "status": result.status.value,
            "response_time_ms": result.response_time_ms,
            "error": result.error,
        }
        for result in results
    ]
    
    logger.info(f"Model status check completed with {len(results)} models checked")
    return {"models": results_dict}
