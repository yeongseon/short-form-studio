"""Storyboard assembly and paragraph operation routes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from creator_service.audio_service import audio_service
from creator_service.script_service import script_service
from creator_service.subtitle_service import subtitle_service
from creator_service.usage_service import check_workspace_quota
from creator_service.visual_asset_service import visual_asset_service
from creator_service.visual_plan_service import visual_plan_service
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from creator_domain.models.pipeline_run import PipelineRun


from shorts_api.routes.storyboard_dispatch import (
    dispatch_storyboard_task_bulk,
    dispatch_storyboard_task_with_tracking,
)
from shorts_api.routes.creator_runs_utils import (
    _has_active_tasks_for_run,
    dispatch_paragraph_audio,
    dispatch_paragraph_subtitles,
    validate_model_key,
    validate_path_id,
)
from shorts_api.auth import CurrentUser, require_run_access

logger = logging.getLogger(__name__)

STORYBOARD_ALLOWED_STAGES = frozenset(
    {
        "VISUAL_ASSET_REVIEW",
        "AUDIO_GENERATING",
        "SUBTITLE_GENERATING",
        "RENDER_GENERATING",
        "FINAL_REVIEW",
    }
)

router = APIRouter(tags=["runs"])




class ParagraphAudioRequest(BaseModel):
    tts_model: str = Field(default="qwen3-tts", max_length=256)
    voice: str = Field(default="default", max_length=256)


class ParagraphSubtitlesRequest(BaseModel):
    subtitle_model: str = Field(default="whisper-small", max_length=256)
    subtitle_format: Literal["srt", "vtt"] = "srt"


class BulkParagraphAudioRequest(BaseModel):
    tts_model: str = Field(default="qwen3-tts", max_length=256)
    voice: str = Field(default="default", max_length=256)


class BulkParagraphSubtitlesRequest(BaseModel):
    subtitle_model: str = Field(default="whisper-small", max_length=256)
    subtitle_format: Literal["srt", "vtt"] = "srt"


@router.get("/runs/{run_id}/storyboard")
async def get_storyboard(
    run_id: int, access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access)
) -> dict[str, object]:
    _, run = access

    draft = await script_service.get_active_draft(run_id)
    if draft is None or not draft.structured_script:
        return {
            "run_id": run_id,
            "paragraphs": [],
            "render_ready": False,
            "total_paragraphs": 0,
            "ready_paragraphs": 0,
        }

    sections = draft.structured_script

    plan = await visual_plan_service.get_active_plan(run_id)
    scene_by_section: dict[str, Any] = {}
    if plan:
        for scene in plan.scenes:
            scene_by_section[scene.section_id] = scene

    grouped_assets = await visual_asset_service.list_by_run(run_id)

    audio_artifacts = await audio_service.list_paragraph_audio(run_id)
    audio_by_section: dict[str, Any] = {}
    for a in audio_artifacts:
        if a.section_id and a.section_id not in audio_by_section:
            audio_by_section[a.section_id] = a

    subtitle_artifacts = await subtitle_service.list_paragraph_subtitles(run_id)
    subtitle_by_section: dict[str, Any] = {}
    for s in subtitle_artifacts:
        if s.section_id and s.section_id not in subtitle_by_section:
            subtitle_by_section[s.section_id] = s

    # Detect paragraph-level generation via active_task_id.
    # Paragraph tasks do not change run.current_stage, so we check whether
    # there are still active Celery tasks tracked on the run.  When tasks
    # are active inside a storyboard-allowed stage we infer per-section
    # generating status from the missing asset type.
    has_active = await _has_active_tasks_for_run(run.id)
    in_storyboard_stage = run.current_stage in STORYBOARD_ALLOWED_STAGES

    paragraphs: list[dict[str, object]] = []
    ready_count = 0

    for idx, section in enumerate(sections):
        scene = scene_by_section.get(section.section_id)
        scene_id = scene.scene_id if scene else None

        image_url: str | None = None
        image_asset_id: int | None = None
        if scene_id and scene_id in grouped_assets:
            for asset in grouped_assets[scene_id]:
                if asset.is_active:
                    image_url = asset.asset_path
                    image_asset_id = asset.id
                    break

        audio = audio_by_section.get(section.section_id)
        audio_url = audio.path if audio else None
        audio_duration = None
        audio_artifact_id = audio.id if audio else None

        subtitle = subtitle_by_section.get(section.section_id)
        subtitles_url = subtitle.path if subtitle else None
        subtitle_artifact_id = subtitle.id if subtitle else None

        has_image = image_url is not None
        has_audio = audio_url is not None
        has_subtitles = subtitles_url is not None

        if has_image and has_audio and has_subtitles:
            status = "ready"
            ready_count += 1
        elif run.current_stage == "VISUAL_ASSET_GENERATING" and not has_image:
            status = "generating_image"
        elif (
            (run.current_stage == "AUDIO_GENERATING" or (has_active and in_storyboard_stage))
            and has_image
            and not has_audio
        ):
            status = "generating_audio"
        elif (
            (run.current_stage == "SUBTITLE_GENERATING" or (has_active and in_storyboard_stage))
            and has_audio
            and not has_subtitles
        ):
            status = "generating_subtitles"
        elif not has_image and not has_audio and not has_subtitles:
            status = "idle"
        else:
            status = "idle"

        paragraphs.append(
            {
                "section_id": section.section_id,
                "order": idx,
                "text": section.text,
                "display_text": section.display_text,
                "image_prompt": scene.prompt if scene else getattr(section, "image_prompt", None),
                "image_url": image_url,
                "audio_url": audio_url,
                "audio_duration": audio_duration,
                "subtitles_url": subtitles_url,
                "subtitle_entries": None,
                "status": status,
                "stale_flags": None,
                "scene_id": scene_id,
                "image_asset_id": image_asset_id,
                "audio_artifact_id": audio_artifact_id,
                "subtitle_artifact_id": subtitle_artifact_id,
                "section_type": section.type,
                "speaker": section.speaker,
                "duration": section.duration,
                "turn_kind": section.turn_kind,
                "visual_override": section.visual_override.model_dump(mode="json")
                if section.visual_override
                else None,
            }
        )

    total = len(paragraphs)
    render_ready = total > 0 and ready_count == total

    return {
        "run_id": run_id,
        "paragraphs": paragraphs,
        "render_ready": render_ready,
        "total_paragraphs": total,
        "ready_paragraphs": ready_count,
    }


@router.post(
    "/runs/{run_id}/storyboard/paragraphs/{section_id}/generate-audio",
    status_code=202,
)
async def generate_paragraph_audio_endpoint(
    run_id: int,
    section_id: str,
    request: ParagraphAudioRequest | None = None,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    effective = request or ParagraphAudioRequest()
    user, run = access
    validate_path_id(section_id, "section_id")
    if run.current_stage not in STORYBOARD_ALLOWED_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot generate storyboard assets in stage '{run.current_stage}'. "
                "Pipeline must be past visual asset review."
            ),
        )

    if getattr(run, "status", None) == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="Run is cancelled; cannot dispatch new tasks",
        )

    draft = await script_service.get_active_draft(run_id)
    if draft is None or not draft.structured_script:
        raise HTTPException(status_code=400, detail="No script available")

    section_text: str | None = None
    for section in draft.structured_script:
        if section.section_id == section_id:
            section_text = section.text
            break

    if section_text is None:
        raise HTTPException(status_code=404, detail=f"Section '{section_id}' not found")

    validate_model_key(effective.tts_model, expected_category="tts")
    allowed, reason = await check_workspace_quota(user.workspace_id, operation_type="tts")
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    task_id = await dispatch_storyboard_task_with_tracking(
        run_id=run_id,
        workspace_id=user.workspace_id,
        operation_type="tts",
        task_type="generate_paragraph_audio",
        dispatch=lambda: dispatch_paragraph_audio(
            run_id=run_id,
            section_id=section_id,
            tts_model=effective.tts_model,
            voice=effective.voice,
        ),
        error_detail="Failed to enqueue paragraph audio task",
    )

    return {
        "task_id": task_id,
        "run_id": run_id,
        "section_id": section_id,
    }


@router.post(
    "/runs/{run_id}/storyboard/paragraphs/{section_id}/generate-subtitles",
    status_code=202,
)
async def generate_paragraph_subtitles_endpoint(
    run_id: int,
    section_id: str,
    request: ParagraphSubtitlesRequest | None = None,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    effective = request or ParagraphSubtitlesRequest()
    user, run = access
    validate_path_id(section_id, "section_id")
    if run.current_stage not in STORYBOARD_ALLOWED_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot generate storyboard assets in stage '{run.current_stage}'. "
                "Pipeline must be past visual asset review."
            ),
        )

    if getattr(run, "status", None) == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="Run is cancelled; cannot dispatch new tasks",
        )

    audio = await audio_service.get_paragraph_audio(run_id, section_id)
    if audio is None:
        raise HTTPException(
            status_code=400,
            detail=f"No audio found for section '{section_id}'. Generate audio first.",
        )

    validate_model_key(effective.subtitle_model, expected_category="stt")
    allowed, reason = await check_workspace_quota(user.workspace_id, operation_type="stt")
    if not allowed:
        raise HTTPException(status_code=429, detail=reason)

    task_id = await dispatch_storyboard_task_with_tracking(
        run_id=run_id,
        workspace_id=user.workspace_id,
        operation_type="stt",
        task_type="generate_paragraph_subtitles",
        dispatch=lambda: dispatch_paragraph_subtitles(
            run_id=run_id,
            section_id=section_id,
            subtitle_model=effective.subtitle_model,
            subtitle_format=effective.subtitle_format,
        ),
        error_detail="Failed to enqueue paragraph subtitle task",
    )

    return {
        "task_id": task_id,
        "run_id": run_id,
        "section_id": section_id,
    }


@router.post("/runs/{run_id}/storyboard/generate-all-audio", status_code=202)
async def generate_all_paragraph_audio(
    run_id: int,
    request: BulkParagraphAudioRequest | None = None,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    effective = request or BulkParagraphAudioRequest()
    user, run = access
    if run.current_stage not in STORYBOARD_ALLOWED_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot generate storyboard assets in stage '{run.current_stage}'. "
                "Pipeline must be past visual asset review."
            ),
        )

    if getattr(run, "status", None) == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="Run is cancelled; cannot dispatch new tasks",
        )

    draft = await script_service.get_active_draft(run_id)
    if draft is None or not draft.structured_script:
        raise HTTPException(status_code=400, detail="No script available")

    validate_model_key(effective.tts_model, expected_category="tts")

    # Skip sections that already have audio artifacts.
    existing_audio = await audio_service.list_paragraph_audio(run_id)
    sections_with_audio: set[str] = set()
    for a in existing_audio:
        if a.section_id:
            sections_with_audio.add(a.section_id)

    task_ids: list[dict[str, str]] = []
    for section in draft.structured_script:
        if section.section_id in sections_with_audio:
            continue
        task_ids.append(
            await dispatch_storyboard_task_bulk(
                run_id=run_id,
                workspace_id=user.workspace_id,
                operation_type="tts",
                task_type="generate_paragraph_audio",
                section_id=section.section_id,
                dispatch=lambda: dispatch_paragraph_audio(
                    run_id=run_id,
                    section_id=section.section_id,
                    tts_model=effective.tts_model,
                    voice=effective.voice,
                ),
            )
        )
    failed_count = sum(1 for t in task_ids if "error" in t)
    return {
        "run_id": run_id,
        "tasks": task_ids,
        "total": len(task_ids),
        "failed": failed_count,
    }


@router.post("/runs/{run_id}/storyboard/generate-all-subtitles", status_code=202)
async def generate_all_paragraph_subtitles(
    run_id: int,
    request: BulkParagraphSubtitlesRequest | None = None,
    access: tuple[CurrentUser, PipelineRun] = Depends(require_run_access),
) -> dict[str, object]:
    effective = request or BulkParagraphSubtitlesRequest()
    user, run = access
    if run.current_stage not in STORYBOARD_ALLOWED_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot generate storyboard assets in stage '{run.current_stage}'. "
                "Pipeline must be past visual asset review."
            ),
        )

    if getattr(run, "status", None) == "cancelled":
        raise HTTPException(
            status_code=409,
            detail="Run is cancelled; cannot dispatch new tasks",
        )

    audio_artifacts = await audio_service.list_paragraph_audio(run_id)
    if not audio_artifacts:
        raise HTTPException(
            status_code=400, detail="No paragraph audio found. Generate audio first."
        )

    validate_model_key(effective.subtitle_model, expected_category="stt")

    # Deduplicate by section_id — only dispatch for the first (latest) audio
    # artifact per section to avoid redundant subtitle generation on regeneration.
    # Also skip sections that already have subtitle artifacts.
    existing_subtitles = await subtitle_service.list_paragraph_subtitles(run_id)
    sections_with_subtitles: set[str] = set()
    for s in existing_subtitles:
        if s.section_id:
            sections_with_subtitles.add(s.section_id)

    seen_sections: set[str] = set()
    task_ids: list[dict[str, str]] = []
    for audio in audio_artifacts:
        section_id = audio.section_id
        if not section_id or section_id in seen_sections:
            continue
        seen_sections.add(section_id)
        if section_id in sections_with_subtitles:
            continue
        task_ids.append(
            await dispatch_storyboard_task_bulk(
                run_id=run_id,
                workspace_id=user.workspace_id,
                operation_type="stt",
                task_type="generate_paragraph_subtitles",
                section_id=section_id,
                dispatch=lambda section_id=section_id: dispatch_paragraph_subtitles(
                    run_id=run_id,
                    section_id=section_id,
                    subtitle_model=effective.subtitle_model,
                    subtitle_format=effective.subtitle_format,
                ),
            )
        )
    failed_count = sum(1 for t in task_ids if "error" in t)
    return {
        "run_id": run_id,
        "tasks": task_ids,
        "total": len(task_ids),
        "failed": failed_count,
    }
