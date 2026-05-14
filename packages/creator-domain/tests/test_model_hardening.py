from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pytest
from pydantic import ValidationError

from creator_domain.models import (
    AudioArtifact,
    ModelSelection,
    ParagraphStatus,
    PipelineRun,
    Project,
    RunStage,
    RunTask,
    ScriptDraft,
    ScriptSection,
    StaleFlags,
    StoryboardParagraph,
    StoryboardResponse,
    SubtitleArtifact,
    UsageEvent,
    UsageSummary,
    User,
    VideoArtifact,
    VisualAsset,
    VisualOverride,
    VisualPlan,
    VisualScene,
    Workspace,
    WorkspaceMember,
    WorkspaceQuota,
)


def _ts() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _pipeline_run_payload() -> dict[str, Any]:
    return {
        "id": 1,
        "project_id": 1,
        "created_at": _ts(),
        "updated_at": _ts(),
    }


def test_pipeline_run_coerces_valid_stage_strings_to_enum() -> None:
    payload = {
        **_pipeline_run_payload(),
        "current_stage": "SCRIPT_REVIEW",
        "review_stage": "VISUAL_PLAN_REVIEW",
        "restart_from": "SCRIPT_GENERATING",
    }
    run = PipelineRun.model_validate(payload)

    assert run.current_stage is RunStage.SCRIPT_REVIEW
    assert run.review_stage is RunStage.VISUAL_PLAN_REVIEW
    assert run.restart_from is RunStage.SCRIPT_GENERATING


def test_pipeline_run_rejects_invalid_stage_strings() -> None:
    with pytest.raises(ValidationError):
        PipelineRun.model_validate({**_pipeline_run_payload(), "current_stage": "NOT_A_STAGE"})


@pytest.mark.parametrize(
    ("factory", "row", "none_field"),
    [
        (
            PipelineRun.from_row,
            {
                "id": 1,
                "project_id": 1,
                "created_at": _ts(),
                "updated_at": _ts(),
                "model_defaults_json": "{bad json",
            },
            "model_defaults",
        ),
        (
            AudioArtifact.from_row,
            {
                "id": 1,
                "run_id": 1,
                "file_path": "a.wav",
                "created_at": _ts(),
                "metadata_json": "{bad json",
            },
            "model_used",
        ),
        (
            SubtitleArtifact.from_row,
            {
                "id": 1,
                "run_id": 1,
                "file_path": "a.srt",
                "created_at": _ts(),
                "metadata_json": "{bad json",
            },
            "section_id",
        ),
        (
            VideoArtifact.from_row,
            {
                "id": 1,
                "run_id": 1,
                "file_path": "a.mp4",
                "created_at": _ts(),
                "metadata_json": "{bad json",
            },
            "render_profile",
        ),
    ],
)
def test_from_row_handles_malformed_json_gracefully(
    factory: Callable[[dict[str, Any]], Any], row: dict[str, Any], none_field: str
) -> None:
    model = factory(row)
    assert getattr(model, none_field) is None


@pytest.mark.parametrize(
    "factory,payload",
    [
        (PipelineRun, _pipeline_run_payload()),
        (Project, {"id": 1, "created_at": _ts(), "updated_at": _ts()}),
        (
            RunTask,
            {
                "id": 1,
                "run_id": 1,
                "task_type": "render",
                "celery_task_id": "abc",
                "created_at": _ts(),
            },
        ),
        (ModelSelection, {}),
        (
            VisualScene,
            {
                "scene_id": "scene-1",
                "section_id": "sec-1",
                "scene_index": 0,
                "section_type": "narration",
                "original_text": "text",
                "prompt": "prompt",
            },
        ),
        (
            VisualPlan,
            {"id": 1, "run_id": 1, "scenes": [], "created_at": _ts()},
        ),
        (
            VisualAsset,
            {
                "id": 1,
                "run_id": 1,
                "scene_id": "scene-1",
                "asset_path": "asset.png",
                "created_at": _ts(),
            },
        ),
        (
            AudioArtifact,
            {
                "id": 1,
                "run_id": 1,
                "path": "audio.wav",
                "created_at": _ts(),
            },
        ),
        (
            SubtitleArtifact,
            {
                "id": 1,
                "run_id": 1,
                "path": "sub.srt",
                "created_at": _ts(),
            },
        ),
        (
            VideoArtifact,
            {
                "id": 1,
                "run_id": 1,
                "path": "video.mp4",
                "created_at": _ts(),
            },
        ),
        (VisualOverride, {"type": "none"}),
        (
            ScriptSection,
            {
                "section_id": "sec-1",
                "type": "narration",
                "text": "hello",
            },
        ),
        (
            ScriptDraft,
            {
                "id": 1,
                "run_id": 1,
                "source_type": "generated_by_model",
                "created_at": _ts(),
            },
        ),
        (
            UsageEvent,
            {
                "id": 1,
                "provider": "openai",
                "model_key": "gpt-4o-mini",
                "operation_type": "script",
                "created_at": _ts(),
            },
        ),
        (
            WorkspaceQuota,
            {
                "id": 1,
                "workspace_id": 1,
                "created_at": _ts(),
                "updated_at": _ts(),
            },
        ),
        (
            UsageSummary,
            {
                "total_llm_calls": 0,
                "total_image_generations": 0,
                "total_tts_seconds": 0.0,
                "total_estimated_cost_usd": 0.0,
                "by_provider": {},
                "by_operation": {},
                "period_start": _ts(),
                "period_end": _ts(),
            },
        ),
        (
            User,
            {"id": 1, "email": "user@example.com", "created_at": _ts(), "updated_at": _ts()},
        ),
        (
            Workspace,
            {
                "id": 1,
                "name": "Acme",
                "slug": "acme",
                "owner_id": 1,
                "created_at": _ts(),
                "updated_at": _ts(),
            },
        ),
        (
            WorkspaceMember,
            {"workspace_id": 1, "user_id": 1, "joined_at": _ts()},
        ),
        (StaleFlags, {}),
        (
            StoryboardParagraph,
            {"section_id": "sec-1", "order": 0, "text": "hello", "status": ParagraphStatus.IDLE},
        ),
        (
            StoryboardResponse,
            {"run_id": 1, "paragraphs": []},
        ),
    ],
)
def test_models_forbid_extra_fields(factory: Callable[..., Any], payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        factory(**payload, unexpected_field="x")


@pytest.mark.parametrize(
    ("factory", "payload"),
    [
        (PipelineRun, {**_pipeline_run_payload(), "id": -1}),
        (
            VisualPlan,
            {"id": 1, "run_id": -1, "scenes": [], "created_at": _ts()},
        ),
        (
            StoryboardParagraph,
            {"section_id": "sec-1", "order": -1, "text": "hello"},
        ),
    ],
)
def test_negative_ids_are_rejected(factory: Callable[..., Any], payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        factory(**payload)


def test_overly_long_scene_and_section_ids_are_rejected() -> None:
    too_long = "x" * 129
    with pytest.raises(ValidationError):
        VisualScene(
            scene_id=too_long,
            section_id="sec-1",
            scene_index=0,
            section_type="narration",
            original_text="text",
            prompt="prompt",
        )

    with pytest.raises(ValidationError):
        ScriptSection(section_id=too_long, type="narration", text="hello")


def test_valid_data_regression_check() -> None:
    run = PipelineRun(
        **_pipeline_run_payload(),
        current_stage=RunStage.SCRIPT_REVIEW,
        model_defaults=ModelSelection(script_model="gpt-4o-mini"),
    )
    assert run.id == 1
    assert run.current_stage == RunStage.SCRIPT_REVIEW
    assert isinstance(run.model_defaults, ModelSelection)

    scene = VisualScene(
        scene_id="scene-1",
        section_id="section-1",
        scene_index=0,
        section_type="narration",
        original_text="hello",
        prompt="prompt",
    )
    assert scene.scene_index == 0
