"""Routes for creator script management."""
import json

from creator_domain.models import RunStage
from creator_domain.models.script_draft import ScriptSection
from creator_service.json_script_parser import parse_json_scenes
from creator_service.markdown_parser import parse_markdown
from creator_service.project_service import project_service
from creator_service.run_service import run_service
from creator_service.script_service import script_service
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, ValidationError

from shorts_api.routes.creator_runs_utils import validate_model_defaults

_SCRIPT_EDIT_STAGES = frozenset({
    RunStage.IDEA_READY.value,
    RunStage.SCRIPT_REVIEW.value,
    RunStage.SCRIPT_GENERATING.value,
})

router = APIRouter(prefix="/projects/{project_id}/script", tags=["script"])
run_script_router = APIRouter(prefix="/runs/{run_id}/script", tags=["script"])


class ImportMarkdownRequest(BaseModel):
    markdown: str = Field(..., max_length=500_000)
    model_defaults: dict[str, str] | None = None
    style_preset: str = "default"


@router.post("/import-markdown", status_code=201)
async def import_markdown(project_id: int, request: ImportMarkdownRequest) -> dict[str, object]:
    if not request.markdown.strip():
        raise HTTPException(status_code=400, detail="markdown content must not be empty")

    project = await project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    validate_model_defaults(request.model_defaults)

    try:
        run = await run_service.create_run(
            project_id=project_id,
            model_defaults=request.model_defaults,
            style_preset=request.style_preset,
            current_stage=RunStage.SCRIPT_REVIEW.value,
            status="running",
        )
        draft = await script_service.save_draft(
            run_id=run.id,
            source_type="pasted_markdown",
            markdown_content=request.markdown,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "project_id": project_id,
        "run_id": run.id,
        "draft": draft.model_dump(mode="json"),
    }


class ImportJsonRequest(BaseModel):
    json_script: str = Field(..., max_length=500_000)
    model_defaults: dict[str, str] | None = None
    style_preset: str = "default"


@router.post("/import-json", status_code=201)
async def import_json(project_id: int, request: ImportJsonRequest) -> dict[str, object]:
    if not request.json_script.strip():
        raise HTTPException(status_code=400, detail="JSON content must not be empty")

    project = await project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    validate_model_defaults(request.model_defaults)

    try:
        sections = parse_json_scenes(request.json_script)
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            raise HTTPException(status_code=400, detail=exc.errors()) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Build markdown from sections for backward compatibility
    rebuilt_markdown = "\n\n".join([f"## {s.type}\n\n{s.text}" for s in sections])

    try:
        run = await run_service.create_run(
            project_id=project_id,
            model_defaults=request.model_defaults,
            style_preset=request.style_preset,
            current_stage=RunStage.SCRIPT_REVIEW.value,
            status="running",
        )
        draft = await script_service.save_draft(
            run_id=run.id,
            source_type="pasted_json",
            markdown_content=rebuilt_markdown,
            structured_script=sections,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "project_id": project_id,
        "run_id": run.id,
        "draft": draft.model_dump(mode="json"),
    }


class UpdateMarkdownRequest(BaseModel):
    markdown: str = Field(..., max_length=500_000)


class UpdateStructuredRequest(BaseModel):
    sections: list[dict[str, object]] = Field(..., max_length=200)


class UpdateJsonScriptRequest(BaseModel):
    json_script: str = Field(..., max_length=500_000)


@run_script_router.get("/markdown")
async def get_script_markdown(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.current_stage not in _SCRIPT_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify script in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_SCRIPT_EDIT_STAGES)}"
            ),
        )

    draft = await script_service.get_active_draft(run_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No script draft found for this run")

    return {
        "run_id": run_id,
        "markdown": draft.markdown_content,
        "version": draft.version,
    }


@run_script_router.get("")
async def get_script(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.current_stage not in _SCRIPT_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify script in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_SCRIPT_EDIT_STAGES)}"
            ),
        )

    draft = await script_service.get_active_draft(run_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No script draft found for this run")

    return {
        "run_id": run_id,
        "script": draft.markdown_content,
        "structured_script": [
            section.model_dump(mode="json")
            for section in (draft.structured_script or [])
        ],
        "version": draft.version,
    }


@run_script_router.get("/structured")
async def get_script_structured(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.current_stage not in _SCRIPT_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify script in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_SCRIPT_EDIT_STAGES)}"
            ),
        )

    draft = await script_service.get_active_draft(run_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No script draft found for this run")

    return {
        "run_id": run_id,
        "sections": [s.model_dump(mode="json") for s in draft.structured_script] if draft.structured_script else [],
        "version": draft.version,
    }


@run_script_router.get("/json")
async def get_script_json(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.current_stage not in _SCRIPT_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify script in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_SCRIPT_EDIT_STAGES)}"
            ),
        )

    draft = await script_service.get_active_draft(run_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No script draft found for this run")

    # Reconstruct JSON from structured_script; handle legacy markdown-era drafts
    scenes: list[dict[str, object]] = []
    if not draft.structured_script:
        # Legacy draft: return empty scenes with a hint rather than 404
        return {
            "run_id": run_id,
            "json_script": json.dumps({"scenes": []}, ensure_ascii=False, indent=2),
            "version": draft.version,
            "legacy": True,
        }

    if draft.structured_script:
        for s in draft.structured_script:
            scene: dict[str, object] = {
                "type": s.type,
                "text": s.text,
            }
            if s.display_text:
                scene["display_text"] = s.display_text
            if s.speaker:
                scene["speaker"] = s.speaker
            if s.duration is not None:
                scene["duration"] = s.duration
            if s.image_prompt:
                scene["image_prompt"] = s.image_prompt
            if s.mood:
                scene["mood"] = s.mood
            if s.composition:
                scene["composition"] = s.composition
            if s.style_tags:
                scene["style_tags"] = s.style_tags
            if s.turn_kind:
                scene["turn_kind"] = s.turn_kind
            scenes.append(scene)

    return {
        "run_id": run_id,
        "json_script": json.dumps({"scenes": scenes}, ensure_ascii=False, indent=2),
        "version": draft.version,
    }


@run_script_router.put("/markdown")
async def update_script_markdown(run_id: int, request: UpdateMarkdownRequest) -> dict[str, object]:
    if not request.markdown.strip():
        raise HTTPException(status_code=400, detail="markdown content must not be empty")

    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.current_stage not in _SCRIPT_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify script in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_SCRIPT_EDIT_STAGES)}"
            ),
        )

    try:
        draft = await script_service.save_draft(
            run_id=run_id,
            source_type="edited_manually",
            markdown_content=request.markdown,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "run_id": run_id,
        "draft": draft.model_dump(mode="json"),
    }


@run_script_router.put("/structured")
async def update_script_structured(run_id: int, request: UpdateStructuredRequest) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.current_stage not in _SCRIPT_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify script in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_SCRIPT_EDIT_STAGES)}"
            ),
        )

    try:
        sections = [ScriptSection.model_validate(section) for section in request.sections]
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.errors()) from exc

    rebuilt_markdown = "\n\n".join([f"## {section.type}\n\n{section.text}" for section in sections])

    draft = await script_service.save_draft(
        run_id=run_id,
        source_type="edited_manually",
        markdown_content=rebuilt_markdown,
        structured_script=sections,
    )

    return {
        "run_id": run_id,
        "draft": draft.model_dump(mode="json"),
    }


@run_script_router.put("/json")
async def update_script_json(run_id: int, request: UpdateJsonScriptRequest) -> dict[str, object]:
    if not request.json_script.strip():
        raise HTTPException(status_code=400, detail="JSON content must not be empty")

    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.current_stage not in _SCRIPT_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify script in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_SCRIPT_EDIT_STAGES)}"
            ),
        )

    try:
        sections = parse_json_scenes(request.json_script)
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            raise HTTPException(status_code=400, detail=exc.errors()) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rebuilt_markdown = "\n\n".join([f"## {s.type}\n\n{s.text}" for s in sections])

    draft = await script_service.save_draft(
        run_id=run_id,
        source_type="pasted_json",
        markdown_content=rebuilt_markdown,
        structured_script=sections,
    )

    return {
        "run_id": run_id,
        "draft": draft.model_dump(mode="json"),
    }


@run_script_router.post("/parse-markdown")
async def parse_script_markdown(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    if run.current_stage not in _SCRIPT_EDIT_STAGES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot modify script in stage '{run.current_stage}'; "
                f"allowed stages: {sorted(_SCRIPT_EDIT_STAGES)}"
            ),
        )

    draft = await script_service.get_active_draft(run_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No script draft found for this run")

    if not draft.markdown_content or not draft.markdown_content.strip():
        raise HTTPException(status_code=400, detail="Draft has no markdown content to parse")

    sections = parse_markdown(
        draft.markdown_content, existing_sections=draft.structured_script
    )

    saved_draft = await script_service.save_draft(
        run_id=run_id,
        source_type=draft.source_type,
        markdown_content=draft.markdown_content,
        structured_script=sections,
    )

    return {
        "run_id": run_id,
        "sections": [s.model_dump(mode="json") for s in sections],
        "version": saved_draft.version,
    }
