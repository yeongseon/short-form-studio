# pyright: reportMissingImports=false

from datetime import datetime, timezone
from typing import Literal, cast

import pytest
from pydantic import BaseModel
from shorts_api.main import projects_router


class StubProject(BaseModel):
    id: int
    title: str
    source_type: Literal["idea", "markdown", "url"]
    idea_brief: str | None = None
    markdown_source: str | None = None
    url_source: str | None = None
    status: str = "draft"
    created_at: datetime
    updated_at: datetime
    latest_run: dict[str, int | str | None] | None = None


class StubProjectService:
    def __init__(self) -> None:
        self.create_project_calls: list[dict[str, object]] = []
        self.get_project_calls: list[int] = []
        self.list_projects_calls: list[tuple[int, int]] = []

        now = datetime.now(timezone.utc)
        self._projects = {
            1: StubProject(
                id=1,
                title="Idea Project",
                source_type="idea",
                idea_brief="Build a daily shorts workflow",
                status="draft",
                created_at=now,
                updated_at=now,
                latest_run={"run_id": 11, "current_stage": "script", "status": "completed"},
            ),
            2: StubProject(
                id=2,
                title="Markdown Project",
                source_type="markdown",
                markdown_source="# Notes",
                status="draft",
                created_at=now,
                updated_at=now,
                latest_run=None,
            ),
        }
        self._next_id = 3

    async def create_project(
        self,
        title: str,
        source_type: str,
        idea_brief: str | None = None,
        markdown_source: str | None = None,
        url_source: str | None = None,
    ) -> StubProject:
        self.create_project_calls.append(
            {
                "title": title,
                "source_type": source_type,
                "idea_brief": idea_brief,
                "markdown_source": markdown_source,
                "url_source": url_source,
            }
        )

        if source_type not in {"idea", "markdown", "url"}:
            raise ValueError(f"Unsupported source_type '{source_type}'")
        if source_type == "idea" and idea_brief is None:
            raise ValueError("source_type='idea' requires idea_brief to be provided")
        if source_type == "markdown" and markdown_source is None:
            raise ValueError("source_type='markdown' requires markdown_source to be provided")
        if source_type == "url" and url_source is None:
            raise ValueError("source_type='url' requires url_source to be provided")

        resolved_source_type = cast(Literal["idea", "markdown", "url"], source_type)

        now = datetime.now(timezone.utc)
        project = StubProject(
            id=self._next_id,
            title=title,
            source_type=resolved_source_type,
            idea_brief=idea_brief,
            markdown_source=markdown_source,
            url_source=url_source,
            status="draft",
            created_at=now,
            updated_at=now,
            latest_run=None,
        )
        self._projects[self._next_id] = project
        self._next_id += 1
        return project

    async def get_project(self, project_id: int) -> StubProject | None:
        self.get_project_calls.append(project_id)
        return self._projects.get(project_id)

    async def list_projects(self, limit: int = 20, offset: int = 0) -> list[StubProject]:
        self.list_projects_calls.append((limit, offset))
        ordered = sorted(self._projects.values(), key=lambda project: project.id)
        return ordered[offset : offset + limit]


    async def count_projects(self) -> int:
        return len(self._projects)

@pytest.fixture
def stub_project_service(monkeypatch: pytest.MonkeyPatch) -> StubProjectService:
    service = StubProjectService()

    for route in projects_router.routes:
        if route.name in {"create_project", "get_project_detail", "list_projects"}:
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", service)

    return service


@pytest.mark.asyncio
async def test_create_project_idea(client, stub_project_service: StubProjectService):
    response = await client.post(
        "/api/creator/projects",
        json={"title": "Idea", "source_type": "idea", "idea_brief": "Use hooks"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source_type"] == "idea"
    assert body["idea_brief"] == "Use hooks"
    assert stub_project_service.create_project_calls[0]["source_type"] == "idea"


@pytest.mark.asyncio
async def test_create_project_markdown(client, stub_project_service: StubProjectService):
    response = await client.post(
        "/api/creator/projects",
        json={"title": "Doc", "source_type": "markdown", "markdown_source": "# Script"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["source_type"] == "markdown"
    assert body["markdown_source"] == "# Script"
    assert stub_project_service.create_project_calls[0]["source_type"] == "markdown"


@pytest.mark.asyncio
async def test_create_project_invalid_source_type(client):
    response = await client.post(
        "/api/creator/projects",
        json={"title": "Bad", "source_type": "invalid", "idea_brief": "Bad source"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_project_url_source_is_not_publicly_supported(client):
    response = await client.post(
        "/api/creator/projects",
        json={"title": "URL", "source_type": "url", "url_source": "https://example.com"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_project_missing_required_field(client, stub_project_service: StubProjectService):
    response = await client.post(
        "/api/creator/projects",
        json={"title": "Missing", "source_type": "idea"},
    )

    assert response.status_code == 400
    assert "requires idea_brief" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_project_found(client, stub_project_service: StubProjectService):
    response = await client.get("/api/creator/projects/1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["latest_run"]["run_id"] == 11
    assert stub_project_service.get_project_calls == [1]


@pytest.mark.asyncio
async def test_get_project_not_found(client, stub_project_service: StubProjectService):
    response = await client.get("/api/creator/projects/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}
    assert stub_project_service.get_project_calls == [999]


@pytest.mark.asyncio
async def test_list_projects_default(client, stub_project_service: StubProjectService):
    response = await client.get("/api/creator/projects")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["projects"], list)
    assert body["total"] == 2
    assert stub_project_service.list_projects_calls == [(20, 0)]


@pytest.mark.asyncio
async def test_list_projects_with_pagination(client, stub_project_service: StubProjectService):
    response = await client.get("/api/creator/projects?limit=1&offset=1")

    assert response.status_code == 200
    body = response.json()
    assert len(body["projects"]) == 1
    assert body["total"] == 2  # total count, not page size
    assert stub_project_service.list_projects_calls == [(1, 1)]
