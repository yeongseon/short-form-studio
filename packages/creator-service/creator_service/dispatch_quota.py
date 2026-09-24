import logging
from importlib import import_module

from creator_domain.exceptions import (
    NotFoundError, QuotaExceededError, ServiceUnavailableError, ValidationError,
)

from creator_service.dispatch_runtime import DispatchRunService

logger = logging.getLogger(__name__)


async def reserve_quota(
    run_service: DispatchRunService, run_id: int,
    *, workspace_id: int | None, operation_type: str | None, owner_id: str | None = None,
) -> int | None:
    if operation_type is None:
        return None
    from creator_service.project_service import project_service
    usage = import_module("creator_service.usage_service")

    try:
        if workspace_id is None:
            run = await run_service.get_run(run_id)
        else:
            try:
                run = await run_service.get_run(run_id, workspace_id=workspace_id)
            except TypeError:
                run = await run_service.get_run(run_id)
        if run is None:
            raise NotFoundError("Run not found")
        if workspace_id is None:
            project = await project_service.get_project(run.project_id)
        else:
            try:
                project = await project_service.get_project(run.project_id, workspace_id=workspace_id)
            except TypeError:
                project = await project_service.get_project(run.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        reservation_workspace = project.workspace_id
        if reservation_workspace is None:
            raise ValidationError("Project workspace is not configured")
        if owner_id is not None:
            allowed, reason = await usage.reserve_owned_quota(reservation_workspace, operation_type, owner_id)
        else:
            allowed, reason = await usage.check_workspace_quota(reservation_workspace, operation_type=operation_type)
        if not allowed:
            raise QuotaExceededError(reason)
        return reservation_workspace
    except (NotFoundError, ValidationError, QuotaExceededError):
        raise
    except Exception:
        logger.exception("Quota check failed", extra={"run_id": run_id})
        raise ServiceUnavailableError("Unable to check quota; dispatch blocked") from None


async def cancel_quota(
    workspace_id: int | None, operation_type: str | None, context: str = "",
    owner_id: str | None = None,
) -> None:
    if workspace_id is None or operation_type is None:
        return
    usage = import_module("creator_service.usage_service")

    try:
        if owner_id is not None:
            await usage.cancel_owned_quota_reservation(owner_id)
        else:
            await usage.cancel_workspace_quota_reservation(workspace_id, operation_type)
    except Exception:
        logger.warning(
            "Failed to cancel quota reservation",
            extra={"workspace_id": workspace_id, "context": context},
        )
