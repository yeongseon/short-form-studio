# pyright: reportMissingImports=false
from creator_service.actionable_errors import build_run_failure_summary, failure_summary_from_code
from creator_service.task_tracking_service import task_tracking_service
from fastapi import APIRouter, Depends
from creator_domain.models.pipeline_run import PipelineRun

from shorts_api.auth import CurrentUser, require_run_access

router = APIRouter(tags=["runs"])


@router.get("/runs/{run_id}/tasks")
async def list_run_tasks(
    run_id: int,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> list[dict[str, object]]:
    _, run = access

    tasks = await task_tracking_service.list_run_tasks(run_id)
    payload: list[dict[str, object]] = []
    for task in tasks:
        item = task.model_dump(mode="json")
        failure = failure_summary_from_code(task.error_code)
        if failure is None and (task.status == "failed" or task.error_message is not None):
            failure = build_run_failure_summary(RuntimeError())
        item["error_message"] = failure["message"] if failure is not None else None
        item["error_code"] = failure["code"] if failure is not None else None
        if failure is not None:
            item["failure"] = failure
        payload.append(item)
    return payload
