"""Generate script task - generates screenplay content."""

from celery_app import celery_app


@celery_app.task
def generate_script(run_id: str) -> dict:
    """
    Generate screenplay script based on run_id.
    
    Args:
        run_id: Unique identifier for the run
        
    Returns:
        Placeholder response with status and run_id
    """
    return {"status": "placeholder", "run_id": run_id}
