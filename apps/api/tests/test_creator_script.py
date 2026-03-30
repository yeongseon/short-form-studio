# pyright: reportMissingImports=false

from datetime import datetime, timezone
from typing import Literal

import pytest
from pydantic import BaseModel

from shorts_api.routes.creator_script import router as script_router, run_script_router


class StubProject(BaseModel):
    id: int
    title: str = "Test Project"


class StubPipelineRun(BaseModel):
    id: int
    project_id: int


class StubScriptDraft(BaseModel):
    id: int
    run_id: int
    source_type: Literal[
        "generated_by_model",
        "pasted_markdown",
        "uploaded_markdown",
        "edited_manually",
    ]
    markdown_content: str | None = None
    structured_script: list[dict[str, object]] | None = None
    version: int = 1
    created_at: datetime


class StubProjectService:
    def __init__(self) -> None:
        self.get_project_calls: list[int] = []
        self.projects: dict[int, StubProject] = {}

    async def get_project(self, project_id: int) -> StubProject | None:
        self.get_project_calls.append(project_id)
        return self.projects.get(project_id)


class StubRunService:
    def __init__(self) -> None:
        self.create_run_calls: list[dict[str, object]] = []
        self.raise_error_message: str | None = None
        self.next_run_id = 1

    async def create_run(
        self,
        project_id: int,
        model_defaults: dict[str, str] | None,
        style_preset: str,
        metadata: dict[str, object] | None = None,
    ) -> StubPipelineRun:
        if self.raise_error_message is not None:
            raise ValueError(self.raise_error_message)

        self.create_run_calls.append(
            {
                "project_id": project_id,
                "model_defaults": model_defaults,
                "style_preset": style_preset,
                "metadata": metadata,
            }
        )
        run = StubPipelineRun(id=self.next_run_id, project_id=project_id)
        self.next_run_id += 1
        return run


class StubRunServiceRead:
    """Minimal run service stub for run-scoped endpoints (get_run only)."""

    def __init__(self) -> None:
        self.runs: dict[int, StubPipelineRun] = {}

    async def get_run(self, run_id: int) -> StubPipelineRun | None:
        return self.runs.get(run_id)

class StubScriptService:
    def __init__(self) -> None:
        self.save_draft_calls: list[dict[str, object]] = []
        self.raise_error_message: str | None = None
        self.next_draft_id = 1
        self.active_drafts: dict[int, StubScriptDraft] = {}

    async def get_active_draft(self, run_id: int) -> StubScriptDraft | None:
        return self.active_drafts.get(run_id)

    async def save_draft(
        self,
        run_id: int,
        source_type: Literal[
            "generated_by_model",
            "pasted_markdown",
            "uploaded_markdown",
            "edited_manually",
        ],
        markdown_content: str,
    ) -> StubScriptDraft:
        if self.raise_error_message is not None:
            raise ValueError(self.raise_error_message)

        self.save_draft_calls.append(
            {
                "run_id": run_id,
                "source_type": source_type,
                "markdown_content": markdown_content,
            }
        )
        current_draft = self.active_drafts.get(run_id)
        next_version = 1 if current_draft is None else current_draft.version + 1

        draft = StubScriptDraft(
            id=self.next_draft_id,
            run_id=run_id,
            source_type=source_type,
            markdown_content=markdown_content,
            structured_script=None,
            version=next_version,
            created_at=datetime.now(timezone.utc),
        )
        self.next_draft_id += 1
        self.active_drafts[run_id] = draft
        return draft


@pytest.fixture
def stub_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubProjectService, StubRunService, StubScriptService]:
    project = StubProjectService()
    run = StubRunService()
    script = StubScriptService()

    for route in script_router.routes:
        monkeypatch.setitem(route.endpoint.__globals__, "project_service", project)
        monkeypatch.setitem(route.endpoint.__globals__, "run_service", run)
        monkeypatch.setitem(route.endpoint.__globals__, "script_service", script)

    return project, run, script


@pytest.fixture
def stub_run_script_services(monkeypatch: pytest.MonkeyPatch) -> tuple[StubRunServiceRead, StubScriptService]:
    run = StubRunServiceRead()
    script = StubScriptService()

    for route in run_script_router.routes:
        monkeypatch.setitem(route.endpoint.__globals__, "run_service", run)
        monkeypatch.setitem(route.endpoint.__globals__, "script_service", script)

    return run, script

@pytest.mark.asyncio
async def test_import_markdown_success(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[11] = StubProject(id=11, title="Project 11")

    response = await client.post(
        "/api/creator/projects/11/script/import-markdown",
        json={"markdown": "# My script\n\nHello world"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == 11
    assert body["run_id"] == 1
    assert body["draft"]["run_id"] == 1
    assert body["draft"]["source_type"] == "pasted_markdown"
    assert body["draft"]["markdown_content"] == "# My script\n\nHello world"
    assert project_service.get_project_calls == [11]
    assert run_service.create_run_calls == [
        {
            "project_id": 11,
            "model_defaults": None,
            "style_preset": "default",
            "metadata": None,
        }
    ]
    assert script_service.save_draft_calls == [
        {
            "run_id": 1,
            "source_type": "pasted_markdown",
            "markdown_content": "# My script\n\nHello world",
        }
    ]


@pytest.mark.asyncio
async def test_import_markdown_project_not_found(client, stub_services):
    _project_service, run_service, script_service = stub_services

    response = await client.post(
        "/api/creator/projects/404/script/import-markdown",
        json={"markdown": "# Missing project"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}
    assert run_service.create_run_calls == []
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_import_markdown_empty_markdown(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[7] = StubProject(id=7, title="Project 7")

    response = await client.post(
        "/api/creator/projects/7/script/import-markdown",
        json={"markdown": ""},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "markdown content must not be empty"}
    assert run_service.create_run_calls == []
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_import_markdown_with_model_defaults(client, stub_services):
    project_service, run_service, _script_service = stub_services
    project_service.projects[21] = StubProject(id=21, title="Project 21")

    response = await client.post(
        "/api/creator/projects/21/script/import-markdown",
        json={
            "markdown": "# Styled script",
            "model_defaults": {
                "script_model": "manual",
                "image_model": "sdxl-base",
                "tts_model": "edge-alloy",
            },
            "style_preset": "cinematic",
        },
    )

    assert response.status_code == 201
    assert run_service.create_run_calls == [
        {
            "project_id": 21,
            "model_defaults": {
                "script_model": "manual",
                "image_model": "sdxl-base",
                "tts_model": "edge-alloy",
            },
            "style_preset": "cinematic",
            "metadata": None,
        }
    ]


@pytest.mark.asyncio
async def test_import_markdown_missing_markdown_field(client, stub_services):
    project_service, _run_service, _script_service = stub_services
    project_service.projects[9] = StubProject(id=9, title="Project 9")

    response = await client.post(
        "/api/creator/projects/9/script/import-markdown",
        json={"style_preset": "default"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_import_markdown_service_error(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[15] = StubProject(id=15, title="Project 15")
    script_service.raise_error_message = "Invalid markdown structure"

    response = await client.post(
        "/api/creator/projects/15/script/import-markdown",
        json={"markdown": "# Broken"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid markdown structure"}
    assert run_service.create_run_calls == [
        {
            "project_id": 15,
            "model_defaults": None,
            "style_preset": "default",
            "metadata": None,
        }
    ]


@pytest.mark.asyncio
async def test_import_markdown_whitespace_only(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[7] = StubProject(id=7, title="Project 7")

    response = await client.post(
        "/api/creator/projects/7/script/import-markdown",
        json={"markdown": "   \n  \t  "},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "markdown content must not be empty"}
    assert run_service.create_run_calls == []
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_import_markdown_create_run_failure(client, stub_services):
    project_service, run_service, script_service = stub_services
    project_service.projects[20] = StubProject(id=20, title="Project 20")
    run_service.raise_error_message = "Duplicate run not allowed"

    response = await client.post(
        "/api/creator/projects/20/script/import-markdown",
        json={"markdown": "# Valid content"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Duplicate run not allowed"}
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_get_script_markdown_success(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[51] = StubPipelineRun(id=51, project_id=1)
    await script_service.save_draft(
        run_id=51,
        source_type="pasted_markdown",
        markdown_content="# Current script\n\nLine",
    )

    response = await client.get("/api/creator/runs/51/script/markdown")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": 51,
        "markdown": "# Current script\n\nLine",
        "version": 1,
    }

@pytest.mark.asyncio
async def test_get_script_markdown_no_draft(client, stub_run_script_services):
    run_service, _script_service = stub_run_script_services
    run_service.runs[999] = StubPipelineRun(id=999, project_id=1)

    response = await client.get("/api/creator/runs/999/script/markdown")

    assert response.status_code == 404
    assert response.json() == {"detail": "No script draft found for this run"}


@pytest.mark.asyncio
async def test_get_script_markdown_run_not_found(client, stub_run_script_services):
    _run_service, _script_service = stub_run_script_services

    response = await client.get("/api/creator/runs/888/script/markdown")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run 888 not found"}

@pytest.mark.asyncio
async def test_update_script_markdown_success(client, stub_run_script_services):
    run_service, script_service = stub_run_script_services
    run_service.runs[42] = StubPipelineRun(id=42, project_id=1)
    await script_service.save_draft(
        run_id=42,
        source_type="pasted_markdown",
        markdown_content="# V1",
    )

    response = await client.put(
        "/api/creator/runs/42/script/markdown",
        json={"markdown": "# V2\n\nUpdated"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 42
    assert body["draft"]["source_type"] == "edited_manually"
    assert body["draft"]["markdown_content"] == "# V2\n\nUpdated"
    assert body["draft"]["version"] == 2
    assert script_service.save_draft_calls[-1] == {
        "run_id": 42,
        "source_type": "edited_manually",
        "markdown_content": "# V2\n\nUpdated",
    }

@pytest.mark.asyncio
async def test_update_script_markdown_run_not_found(client, stub_run_script_services):
    _run_service, script_service = stub_run_script_services

    response = await client.put(
        "/api/creator/runs/77/script/markdown",
        json={"markdown": "# Fresh draft"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Run 77 not found"}
    assert script_service.save_draft_calls == []


@pytest.mark.asyncio
async def test_update_script_markdown_first_draft(client, stub_run_script_services):
    """PUT /markdown succeeds when run exists but no prior draft (creates first draft)."""
    run_service, script_service = stub_run_script_services
    run_service.runs[77] = StubPipelineRun(id=77, project_id=1)

    response = await client.put(
        "/api/creator/runs/77/script/markdown",
        json={"markdown": "# Fresh draft"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 77
    assert body["draft"]["version"] == 1
    assert body["draft"]["source_type"] == "edited_manually"
    assert body["draft"]["markdown_content"] == "# Fresh draft"
    assert script_service.active_drafts[77].version == 1

@pytest.mark.asyncio
async def test_update_script_markdown_empty(client, stub_run_script_services):
    _run_service, script_service = stub_run_script_services

    response = await client.put(
        "/api/creator/runs/13/script/markdown",
        json={"markdown": ""},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "markdown content must not be empty"}
    assert script_service.save_draft_calls == []

@pytest.mark.asyncio
async def test_update_script_markdown_whitespace_only(client, stub_run_script_services):
    _run_service, script_service = stub_run_script_services

    response = await client.put(
        "/api/creator/runs/13/script/markdown",
        json={"markdown": "   \n\t  "},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "markdown content must not be empty"}
    assert script_service.save_draft_calls == []
