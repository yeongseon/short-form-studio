import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from decimal import Decimal
from importlib import import_module
from uuid import uuid4

from creator_domain.exceptions import ConflictError, NotFoundError, ServiceError, ServiceUnavailableError
from creator_domain.task_dispatch import SynchronousTaskExecutionError
from pydantic import JsonValue

from creator_service.dispatch_quota import cancel_quota, reserve_quota
from creator_service.blocking_io import owned_operation, run_blocking, run_control
from creator_service.dispatch_runtime import DispatchRun, DispatchRunService, DispatchRuntime

logger = logging.getLogger(__name__)

_DISPATCH_TASK_TYPES = {
    "dispatch_generate_script": "generate_script",
    "dispatch_generate_visual_plan": "generate_visual_plan",
    "dispatch_generate_audio": "generate_audio",
    "dispatch_generate_subtitles": "generate_subtitles",
    "dispatch_render_video": "render_video",
    "dispatch_generate_scene_image": "generate_scene_image",
    "dispatch_paragraph_audio": "generate_paragraph_audio",
    "dispatch_paragraph_subtitles": "generate_paragraph_subtitles",
}


@dataclass(frozen=True, slots=True)
class StageRollback:
    run_id: int
    target_stage: str
    previous_stage: str
    restart_from: str | None
    workspace_id: int | None

    async def apply(self, service: DispatchRunService) -> None:
        try:
            await service.storage.conditional_update_run(
                self.run_id, {"current_stage": self.previous_stage, "restart_from": self.restart_from},
                expected_stages=frozenset({self.target_stage}), workspace_id=self.workspace_id,
            )
        except Exception:
            logger.warning("Failed to rollback CAS", extra={"run_id": self.run_id}, exc_info=True)


async def read_run(service: DispatchRunService, run_id: int, workspace_id: int | None) -> DispatchRun | None:
    if workspace_id is None:
        return await service.get_run(run_id)
    try:
        return await service.get_run(run_id, workspace_id=workspace_id)
    except TypeError:
        return await service.get_run(run_id)


class DispatchCAS(DispatchRuntime):
    _cancel_quota_safe = staticmethod(cancel_quota)

    async def _cancel_task_safe(self, task_id: str) -> None:
        try:
            await run_control(partial(self.dispatcher.cancel, task_id))
        except Exception:
            logger.warning("Failed to revoke task", extra={"task_id": task_id}, exc_info=True)

    @owned_operation
    async def cas_dispatch_with_rollback(
        self, *, run_id: int, expected_stages: frozenset[str], target_stage: str,
        dispatcher: Callable[..., str], dispatcher_args: Mapping[str, JsonValue],
        run_service: DispatchRunService, rollback_stage: str, rollback_restart_from: str | None,
        enqueue_error_detail: str, restart_from_stage: str | None = None,
        quota_operation_type: str | None = None, workspace_id: int | None = None,
        reservation_estimate_usd: Decimal | None = None,
        reservation_units: int = 1,
        reservation_owner_id: str | None = None,
    ) -> dict[str, JsonValue]:
        task_tracking_service = import_module("creator_service.task_tracking_service").task_tracking_service
        rollback = StageRollback(
            run_id, target_stage, rollback_stage, rollback_restart_from, workspace_id,
        )
        dispatch_prepared = False

        try:
            try:
                pre_run = await read_run(run_service, run_id, workspace_id)
            except Exception:
                logger.exception("Pre-dispatch run check failed", extra={"run_id": run_id})
                raise ServiceUnavailableError("Unable to verify run status; dispatch blocked") from None
            if pre_run is None:
                raise NotFoundError("Run not found")
            if getattr(pre_run, "status", None) == "cancelled":
                raise ConflictError("Run is cancelled; cannot dispatch new tasks")

            task_type = _DISPATCH_TASK_TYPES.get(getattr(dispatcher, "__name__", ""), "unknown")
            owner_id = reservation_owner_id
            if owner_id is None and quota_operation_type is not None and task_type != "unknown":
                owner_id = str(uuid4())
            reserved_workspace = await reserve_quota(
                run_service, run_id, workspace_id=workspace_id, operation_type=quota_operation_type,
                owner_id=owner_id, estimated_cost_usd=reservation_estimate_usd,
                units=reservation_units,
            )
            dispatch_prepared = True
        finally:
            if reservation_owner_id is not None and not dispatch_prepared:
                await cancel_quota(
                    workspace_id, quota_operation_type, "before stage update", reservation_owner_id,
                )
                await rollback.apply(run_service)
        if reserved_workspace is not None:
            workspace_id = reserved_workspace
        rollback = StageRollback(run_id, target_stage, rollback_stage, rollback_restart_from, workspace_id)
        updates: dict[str, JsonValue] = {"current_stage": target_stage}
        if rollback_stage == (restart_from_stage or target_stage):
            updates["restart_from"] = target_stage
        pending_id: str | None = None
        broker_generation: str | None = None
        if self._use_celery_dispatch() and task_type != "unknown":
            pending_id = owner_id or str(uuid4())
            try:
                broker_generation = await run_blocking(self.broker_generation)
            except Exception:
                await cancel_quota(
                    reserved_workspace,
                    quota_operation_type,
                    "while reading broker generation",
                    owner_id,
                )
                raise ServiceUnavailableError(
                    "Unable to verify broker generation; dispatch blocked"
                ) from None
        try:
            if pending_id is None:
                try:
                    ok, row = await run_service.storage.conditional_update_run(
                        run_id, updates, expected_stages=expected_stages,
                        workspace_id=workspace_id, rejected_statuses=frozenset({"cancelled"}),
                    )
                except TypeError:
                    ok, row = await run_service.storage.conditional_update_run(
                        run_id, updates, expected_stages=expected_stages,
                        workspace_id=workspace_id,
                    )
            else:
                ok, row = await task_tracking_service.transition_run_and_record_pending(
                    run_service.storage, run_id, updates, expected_stages,
                    task_type, pending_id, workspace_id=workspace_id,
                    broker_generation=broker_generation,
                    rejected_statuses=frozenset({"cancelled"}),
                )
        except ServiceError:
            await cancel_quota(reserved_workspace, quota_operation_type, "during stage update", owner_id)
            raise
        except Exception:
            await cancel_quota(reserved_workspace, quota_operation_type, "during stage update", owner_id)
            raise ServiceUnavailableError("Storage failure during dispatch stage update") from None
        if not ok:
            await cancel_quota(reserved_workspace, quota_operation_type, owner_id=owner_id)
            if row is None:
                raise NotFoundError("Run not found")
            raise ConflictError(f"Stage conflict: run is now in '{row.get('current_stage')}'")

        try:
            dispatch_kwargs = dict(dispatcher_args)
            if pending_id is not None or owner_id is not None:
                dispatch_kwargs["task_id"] = pending_id or owner_id
            task_id = await run_blocking(partial(dispatcher, **dispatch_kwargs))
            if owner_id is not None and task_id != owner_id:
                raise ServiceUnavailableError("Task identity changed during dispatch")
            if broker_generation is not None:
                observed_generation = await run_blocking(self.broker_generation)
                if observed_generation != broker_generation:
                    await self._cancel_task_safe(task_id)
                    try:
                        await task_tracking_service.mark_revoked(task_id)
                    except Exception:
                        logger.warning(
                            "Failed to mark uncertain task revoked",
                            extra={"task_id": task_id},
                            exc_info=True,
                        )
                    raise ServiceUnavailableError("Broker generation changed during dispatch")
        except SynchronousTaskExecutionError:
            await cancel_quota(reserved_workspace, quota_operation_type, owner_id=owner_id)
            raise ServiceError("Task execution failed") from None
        except Exception:
            await cancel_quota(reserved_workspace, quota_operation_type, owner_id=owner_id)
            await rollback.apply(run_service)
            raise ServiceUnavailableError(enqueue_error_detail) from None

        try:
            if task_type != "unknown" and not task_id.startswith("sync-"):
                if pending_id is not None:
                    await task_tracking_service.promote_pending_to_queued(pending_id)
                else:
                    await task_tracking_service.record_task_queued(run_id, task_type, task_id)
        except Exception:
            await self._cancel_task_safe(task_id)
            try:
                await task_tracking_service.mark_revoked(task_id)
            except Exception:
                logger.warning("Failed to mark task revoked during rollback", extra={"task_id": task_id}, exc_info=True)
            await cancel_quota(reserved_workspace, quota_operation_type, "during rollback", owner_id)
            await rollback.apply(run_service)
            raise ServiceUnavailableError(enqueue_error_detail) from None

        try:
            post_run = await read_run(run_service, run_id, workspace_id)
        except Exception:
            post_run = None
        if post_run is None or getattr(post_run, "status", None) == "cancelled":
            await self._cancel_task_safe(task_id)
            try:
                await task_tracking_service.mark_tasks_revoked([task_id])
            except Exception:
                logger.warning("Failed to mark task revoked", extra={"task_id": task_id}, exc_info=True)
            await rollback.apply(run_service)
            await cancel_quota(reserved_workspace, quota_operation_type, "during concurrent cancel", owner_id)
            raise ConflictError("Run was cancelled during dispatch")
        return {"task_id": task_id, "run_id": run_id, "current_stage": target_stage}
