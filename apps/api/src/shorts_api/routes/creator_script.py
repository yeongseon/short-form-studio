"""Routes for creator script management."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ValidationError

from creator_domain.models.script_draft import ScriptSection
from creator_service.markdown_parser import parse_markdown
from creator_service.project_service import project_service
from creator_service.run_service import run_service
from creator_service.script_service import script_service

router = APIRouter(prefix="/projects/{project_id}/script", tags=["script"])
run_script_router = APIRouter(prefix="/runs/{run_id}/script", tags=["script"])


class ImportMarkdownRequest(BaseModel):
    markdown: str
    model_defaults: dict[str, str] | None = None
    style_preset: str = "default"


@router.post("/import-markdown", status_code=201)
async def import_markdown(project_id: int, request: ImportMarkdownRequest) -> dict[str, object]:
    if not request.markdown.strip():
        raise HTTPException(status_code=400, detail="markdown content must not be empty")

    project = await project_service.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        run = await run_service.create_run(
            project_id=project_id,
            model_defaults=request.model_defaults,
            style_preset=request.style_preset,
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


class UpdateMarkdownRequest(BaseModel):
    markdown: str


class UpdateStructuredRequest(BaseModel):
    sections: list[dict[str, object]]


@run_script_router.get("/markdown")
async def get_script_markdown(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    draft = await script_service.get_active_draft(run_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No script draft found for this run")

    return {
        "run_id": run_id,
        "markdown": draft.markdown_content,
        "version": draft.version,
    }


@run_script_router.get("/structured")
async def get_script_structured(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    draft = await script_service.get_active_draft(run_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="No script draft found for this run")

    return {
        "run_id": run_id,
        "sections": [s.model_dump(mode="json") for s in draft.structured_script] if draft.structured_script else [],
        "version": draft.version,
    }


@run_script_router.put("/markdown")
async def update_script_markdown(run_id: int, request: UpdateMarkdownRequest) -> dict[str, object]:
    if not request.markdown.strip():
        raise HTTPException(status_code=400, detail="markdown content must not be empty")

    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

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

    try:
        sections = [ScriptSection.model_validate(section) for section in request.sections]
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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


@run_script_router.post("/parse-markdown")
async def parse_script_markdown(run_id: int) -> dict[str, object]:
    run = await run_service.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

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
