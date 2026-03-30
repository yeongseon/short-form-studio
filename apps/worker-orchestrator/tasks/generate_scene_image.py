"""Generate scene image task - generates individual scene images."""

from celery_app import celery_app


@celery_app.task
def generate_scene_image(run_id: str, scene_id: str) -> dict:
    """
    Generate image for a specific scene.
    
    Args:
        run_id: Unique identifier for the run
        scene_id: Unique identifier for the scene
        
    Returns:
        Placeholder response with status, run_id, and scene_id
    """
    return {"status": "placeholder", "run_id": run_id, "scene_id": scene_id}
