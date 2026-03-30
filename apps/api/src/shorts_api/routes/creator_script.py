"""Routes for creator script management."""
# pyright: reportMissingImports=false

import os
import sys

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# Add packages to path for imports
_PACKAGES_DIR = os.path.join(os.path.dirname(__file__), "../../../../..", "packages")
sys.path.insert(0, _PACKAGES_DIR)
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-service"))
sys.path.insert(0, os.path.join(_PACKAGES_DIR, "creator-provider"))

try:
    from creator_service.project_service import project_service
except ImportError:
    from project_service import project_service

try:
    from creator_service.run_service import run_service
except ImportError:
    from run_service import run_service

try:
    from creator_service.script_service import script_service
except ImportError:
    from script_service import script_service

router = APIRouter(prefix="/projects/{project_id}/script", tags=["script"])


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
