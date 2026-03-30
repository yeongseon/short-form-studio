import asyncio
import sys
from pathlib import Path
from typing import Any, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "creator-domain"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_service import InMemoryProjectStorage, ProjectService


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def storage() -> InMemoryProjectStorage:
    return InMemoryProjectStorage()


@pytest.fixture
def service(storage: InMemoryProjectStorage) -> ProjectService:
    return ProjectService(storage)


def test_create_project_with_idea_source_type(service: ProjectService) -> None:
    project = run(
        service.create_project(
            title="Idea Project",
            source_type="idea",
            idea_brief="Build a short-form video script from one concept.",
        )
    )

    assert project.id == 1
    assert project.title == "Idea Project"
    assert project.source_type == "idea"
    assert project.idea_brief == "Build a short-form video script from one concept."
    assert project.markdown_source is None
    assert project.url_source is None
    assert project.status == "draft"


def test_create_project_with_markdown_source_type(service: ProjectService) -> None:
    markdown = "# Topic\n\nTurn this into a video script."
    project = run(
        service.create_project(
            title="Markdown Project",
            source_type="markdown",
            markdown_source=markdown,
        )
    )

    assert project.title == "Markdown Project"
    assert project.source_type == "markdown"
    assert project.markdown_source == markdown
    assert project.idea_brief is None
    assert project.url_source is None


def test_create_project_with_invalid_source_type_raises_value_error(service: ProjectService) -> None:
    with pytest.raises(ValueError, match="Unsupported source_type"):
        run(service.create_project(title="Invalid", source_type=cast(Any, "pdf")))


def test_get_project_returns_none_for_missing_project(service: ProjectService) -> None:
    assert run(service.get_project(9999)) is None


def test_get_project_returns_existing_project(service: ProjectService) -> None:
    created = run(service.create_project(title="Existing", source_type="url", url_source="https://example.com"))
    fetched = run(service.get_project(created.id))

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.title == "Existing"
    assert fetched.source_type == "url"
    assert fetched.url_source == "https://example.com"
    assert fetched.model_dump()["latest_run"] is None


def test_list_projects_returns_newest_first(service: ProjectService) -> None:
    older = run(service.create_project(title="Older", source_type="idea", idea_brief="old"))
    newer = run(service.create_project(title="Newer", source_type="idea", idea_brief="new"))

    projects = run(service.list_projects())

    assert [project.id for project in projects[:2]] == [newer.id, older.id]


def test_list_projects_respects_limit_and_offset(service: ProjectService) -> None:
    first = run(service.create_project(title="First", source_type="idea"))
    second = run(service.create_project(title="Second", source_type="idea"))
    third = run(service.create_project(title="Third", source_type="idea"))

    projects = run(service.list_projects(limit=1, offset=1))

    assert len(projects) == 1
    assert projects[0].id == second.id
    assert projects[0].title == "Second"
    assert first.id != projects[0].id
    assert third.id != projects[0].id


def test_get_and_list_include_latest_run_summary(
    service: ProjectService,
    storage: InMemoryProjectStorage,
) -> None:
    project = run(service.create_project(title="With Run", source_type="idea"))

    run(storage.insert_run(project.id, current_stage="script_generating", status="running"))
    latest = run(storage.insert_run(project.id, current_stage="script_review", status="paused"))

    detailed = run(service.get_project(project.id))
    listed = run(service.list_projects())

    assert detailed is not None
    assert detailed.model_dump()["latest_run"] == {
        "run_id": latest["id"],
        "current_stage": "script_review",
        "status": "paused",
    }
    assert listed[0].model_dump()["latest_run"] == {
        "run_id": latest["id"],
        "current_stage": "script_review",
        "status": "paused",
    }
