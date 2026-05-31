"""Core run CRUD, approvals, and script trigger routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from creator_domain.models import TRIGGER_POLICY
from creator_service.project_service import project_service
from creator_service.run_service import ConflictError, run_service
from creator_service.stage_review_service import stage_review_service
from creator_service.task_dispatch_service import (
    cas_dispatch_with_rollback,
    dispatch_generate_script,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun
    from creator_domain.models.project import Project


from shorts_api.auth import CurrentUser, require_project_access, require_run_access
from shorts_api.routes.creator_runs_utils import (
    _has_active_tasks_for_run,
    validate_model_defaults,
    validate_model_key,
)

router = APIRouter(tags=["runs"])


class CreateRunRequest(BaseModel):
    model_defaults: dict[str, str] | None = None
    style_preset: str = Field(default="default", max_length=256)
    metadata: dict[str, object] | None = None


class RestartRunRequest(BaseModel):
    stage: Literal[
        "IDEA_READY",
        "SCRIPT_GENERATING",
        "SCRIPT_REVIEW",
        "VISUAL_PLAN_SETUP",
        "VISUAL_PLAN_GENERATING",
        "VISUAL_PLAN_REVIEW",
        "VISUAL_ASSET_GENERATING",
        "VISUAL_ASSET_REVIEW",
        "AUDIO_GENERATING",
        "SUBTITLE_GENERATING",
        "RENDER_GENERATING",
        "FINAL_REVIEW",
        "PUBLISHED",
        "FAILED",
    ]


class ApproveScriptRequest(BaseModel):
    reviewer: str = Field(default="agent", max_length=256)
    notes: str | None = Field(default=None, max_length=1000)


class ApproveVisualPlanRequest(BaseModel):
    reviewer: str = Field(default="agent", max_length=256)
    notes: str | None = Field(default=None, max_length=1000)


class ApproveVisualAssetsRequest(BaseModel):
    reviewer: str = Field(default="agent", max_length=256)
    notes: str | None = Field(default=None, max_length=1000)


class GenerateScriptRequest(BaseModel):
    model_key: str = Field(default="qwen3-4b", max_length=256)
    instructions: str | None = Field(default=None, max_length=32_000)


class GenerateVisualPlanRequest(BaseModel):
    model_key: str = Field(default="qwen3-4b", max_length=256)
    style_preset: str | None = Field(default=None, max_length=200)


class GenerateAudioRequest(BaseModel):
    tts_model: str = Field(default="qwen3-tts", max_length=256)
    voice: str = Field(default="default", max_length=256)


class GenerateSubtitlesRequest(BaseModel):
    subtitle_model: str = Field(default="whisper-small", max_length=256)
    subtitle_format: Literal["srt", "vtt"] = "srt"


class RenderRequest(BaseModel):
    render_profile: str = Field(default="shorts_default", max_length=256)


class UpdateModelDefaultsRequest(BaseModel):
    script_model: str | None = Field(default=None, max_length=256)
    image_model: str | None = Field(default=None, max_length=256)
    tts_model: str | None = Field(default=None, max_length=256)
    subtitle_model: str | None = Field(default=None, max_length=256)
    render_profile: str | None = Field(default=None, max_length=256)


@router.post("/projects/{project_id}/runs", status_code=201)
async def create_run(
    project_id: int,
    request: CreateRunRequest,
    access: tuple[CurrentUser, Project] = Depends(require_project_access),
) -> dict[str, object]:
    user, project = access

    # Reject if project is being deleted — prevents TOCTOU race where a
    # new run could be created after delete_project enumerates runs but
    # before the final DB delete, orphaning the new run's artifacts.
    if getattr(project, "status", None) == "deleting":
        raise HTTPException(
            status_code=409,
            detail="Project is being deleted; cannot create new runs",
        )

    validate_model_defaults(request.model_defaults)

    try:
        run = await run_service.create_run(
            project_id=project_id,
            model_defaults=request.model_defaults,
            style_preset=request.style_preset,
            metadata=request.metadata,
            workspace_id=user.workspace_id,
        )
    except ConflictError:
        raise HTTPException(
            status_code=409,
            detail="Project is being deleted; cannot create new runs",
        )
    return run.model_dump(mode="json")


@router.get("/projects/{project_id}/runs")
async def list_runs_for_project(
    project_id: int, access: tuple[CurrentUser, Project] = Depends(require_project_access)
) -> dict[str, object]:
    user, _ = access
    runs = await run_service.list_runs_by_project(project_id, workspace_id=user.workspace_id)
    return {
        "runs": [r.model_dump(mode="json") for r in runs],
        "total": len(runs),
    }


@router.get("/runs/{run_id}")
async def get_run_detail(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    _, run = access
    return run.model_dump(mode="json")


@router.post("/runs/{run_id}/restart")
async def restart_run(
    run_id: int,
    request: RestartRunRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, _ = access
    try:
        run = await run_service.restart_run(
            run_id=run_id,
            from_stage=request.stage,
            workspace_id=user.workspace_id,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return run.model_dump(mode="json")


@router.post("/runs/{run_id}/approve-script")
async def approve_script(
    run_id: int,
    request: ApproveScriptRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, _ = access
    try:
        updated_run = await stage_review_service.approve_and_advance(
            run_service=run_service,
            run_id=run_id,
            stage_name="SCRIPT_REVIEW",
            target_stage="VISUAL_PLAN_SETUP",
            reviewer=request.reviewer,
            notes=request.notes,
            workspace_id=user.workspace_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        if "conflict" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated_run.model_dump(mode="json")


@router.post("/runs/{run_id}/approve-visual-plan")
async def approve_visual_plan(
    run_id: int,
    request: ApproveVisualPlanRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, _ = access
    try:
        updated_run = await stage_review_service.approve_and_advance(
            run_service=run_service,
            run_id=run_id,
            stage_name="VISUAL_PLAN_REVIEW",
            target_stage="VISUAL_ASSET_GENERATING",
            reviewer=request.reviewer,
            notes=request.notes,
            workspace_id=user.workspace_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        if "conflict" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated_run.model_dump(mode="json")


@router.post("/runs/{run_id}/approve-visual-assets")
async def approve_visual_assets(
    run_id: int,
    request: ApproveVisualAssetsRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, _ = access
    try:
        updated_run = await stage_review_service.approve_and_advance(
            run_service=run_service,
            run_id=run_id,
            stage_name="VISUAL_ASSET_REVIEW",
            target_stage="AUDIO_GENERATING",
            reviewer=request.reviewer,
            notes=request.notes,
            workspace_id=user.workspace_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        if "conflict" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated_run.model_dump(mode="json")


class ApproveFinalRequest(BaseModel):
    reviewer: str = Field(default="agent", max_length=256)
    notes: str | None = Field(default=None, max_length=1000)


@router.post("/runs/{run_id}/approve-final")
async def approve_final(
    run_id: int,
    request: ApproveFinalRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, _ = access
    try:
        updated_run = await stage_review_service.approve_and_advance(
            run_service=run_service,
            run_id=run_id,
            stage_name="FINAL_REVIEW",
            target_stage="PUBLISHED",
            reviewer=request.reviewer,
            notes=request.notes,
            workspace_id=user.workspace_id,
        )
        # Mark run as completed
        updated_run = await run_service.mark_completed(
            run_id,
            workspace_id=user.workspace_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(status_code=404, detail=detail) from exc
        if "conflict" in detail.lower():
            raise HTTPException(status_code=409, detail=detail) from exc
        raise HTTPException(status_code=400, detail=detail) from exc

    return updated_run.model_dump(mode="json")

@router.post("/runs/{run_id}/generate-script", status_code=202)
async def generate_script_trigger(
    run_id: int,
    request: GenerateScriptRequest,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    user, run = access
    if run.current_stage == "SCRIPT_GENERATING" and await _has_active_tasks_for_run(run.id):
        raise HTTPException(status_code=409, detail="Script generation already in progress")

    allowed_stages = frozenset(stage.value for stage in TRIGGER_POLICY["generate_script"])
    if run.current_stage not in allowed_stages:
        raise HTTPException(
            status_code=409,
            detail=f"Run is in stage '{run.current_stage}', "
            f"expected one of {sorted(allowed_stages)}",
        )

    project = await project_service.get_project(run.project_id, workspace_id=user.workspace_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    validate_model_key(request.model_key, expected_category="llm")
    idea_brief = project.idea_brief or project.title or ""

    return await cas_dispatch_with_rollback(
        run_id=run_id,
        expected_stages=allowed_stages,
        target_stage="SCRIPT_GENERATING",
        dispatcher=dispatch_generate_script,
        dispatcher_args={
            "run_id": run_id,
            "idea_brief": idea_brief,
            "model_key": request.model_key,
            "instructions": request.instructions,
        },
        run_service=run_service,
        rollback_stage=run.current_stage,
        rollback_restart_from=run.restart_from,
        enqueue_error_detail="Failed to enqueue script generation task",
        restart_from_stage="SCRIPT_REVIEW",
        quota_operation_type="llm",
        workspace_id=user.workspace_id,
    )
