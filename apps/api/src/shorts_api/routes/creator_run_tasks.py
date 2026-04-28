from creator_service.run_service import run_service
from creator_service.task_tracking_service import task_tracking_service
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/tasks")
async def list_run_tasks(run_id: int) -> list[dict[str, object]]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    tasks = await task_tracking_service.list_run_tasks(run_id)
    return [task.model_dump(mode="json") for task in tasks]
