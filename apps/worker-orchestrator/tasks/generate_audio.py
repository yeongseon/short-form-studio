"""Generate audio task - generates audio content."""

from celery_app import celery_app


@celery_app.task
def generate_audio(run_id: str) -> dict:
    """
    Generate audio content based on run_id.
    
    Args:
        run_id: Unique identifier for the run
        
    Returns:
        Placeholder response with status and run_id
    """
    return {"status": "placeholder", "run_id": run_id}
