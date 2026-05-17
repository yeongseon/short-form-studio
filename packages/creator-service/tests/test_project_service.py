import asyncio
from typing import Any, cast

import pytest
from creator_service.project_service import InMemoryProjectStorage, ProjectService
from creator_service.run_service import InMemoryRunStorage, RunService


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


def test_create_project_with_invalid_source_type_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(ValueError, match="Unsupported source_type"):
        run(service.create_project(title="Invalid", source_type=cast(Any, "pdf")))


def test_get_project_returns_none_for_missing_project(service: ProjectService) -> None:
    assert run(service.get_project(9999)) is None


def test_get_project_returns_existing_project(service: ProjectService) -> None:
    created = run(
        service.create_project(
            title="Existing", source_type="url", url_source="https://example.com"
        )
    )
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
    first = run(service.create_project(title="First", source_type="idea", idea_brief="first idea"))
    second = run(
        service.create_project(title="Second", source_type="idea", idea_brief="second idea")
    )
    third = run(service.create_project(title="Third", source_type="idea", idea_brief="third idea"))

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
    project = run(
        service.create_project(title="With Run", source_type="idea", idea_brief="test idea")
    )

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


def test_get_and_list_include_latest_run_summary_from_run_service(
    service: ProjectService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = run(
        service.create_project(title="With Real Run", source_type="idea", idea_brief="test idea")
    )

    run_service = RunService(InMemoryRunStorage())
    first = run(
        run_service.create_run(
            project_id=project.id,
            model_defaults=None,
            style_preset="default",
        )
    )
    second = run(
        run_service.create_run(
            project_id=project.id,
            model_defaults=None,
            style_preset="default",
        )
    )

    run(run_service.advance_stage(second.id, "SCRIPT_GENERATING"))

    import creator_service.run_service as run_service_module

    monkeypatch.setattr(run_service_module, "run_service", run_service)

    detailed = run(service.get_project(project.id))
    listed = run(service.list_projects())

    assert detailed is not None
    assert detailed.model_dump()["latest_run"] == {
        "run_id": second.id,
        "current_stage": "SCRIPT_GENERATING",
        "status": "pending",
    }
    assert listed[0].model_dump()["latest_run"] == {
        "run_id": second.id,
        "current_stage": "SCRIPT_GENERATING",
        "status": "pending",
    }
    assert first.id != second.id


def test_create_project_with_markdown_missing_source_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(ValueError, match="source_type='markdown' requires markdown_source"):
        run(service.create_project(title="Bad Markdown", source_type="markdown"))


def test_create_project_with_url_missing_source_raises_value_error(service: ProjectService) -> None:
    with pytest.raises(ValueError, match="source_type='url' requires url_source"):
        run(service.create_project(title="Bad URL", source_type="url"))


def test_create_project_with_idea_missing_brief_raises_value_error(service: ProjectService) -> None:
    with pytest.raises(ValueError, match="source_type='idea' requires idea_brief"):
        run(service.create_project(title="Bad Idea", source_type="idea"))


def test_create_project_idea_with_markdown_source_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(
        ValueError, match="source_type='idea' cannot have markdown_source or url_source set"
    ):
        run(
            service.create_project(
                title="Conflicting Fields",
                source_type="idea",
                idea_brief="My idea",
                markdown_source="# This should not be here",
            )
        )


def test_create_project_idea_with_url_source_raises_value_error(service: ProjectService) -> None:
    with pytest.raises(
        ValueError, match="source_type='idea' cannot have markdown_source or url_source set"
    ):
        run(
            service.create_project(
                title="Conflicting Fields",
                source_type="idea",
                idea_brief="My idea",
                url_source="https://example.com",
            )
        )


def test_create_project_markdown_with_url_source_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(
        ValueError, match="source_type='markdown' cannot have idea_brief or url_source set"
    ):
        run(
            service.create_project(
                title="Conflicting Fields",
                source_type="markdown",
                markdown_source="# Content",
                url_source="https://example.com",
            )
        )


def test_create_project_markdown_with_idea_brief_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(
        ValueError, match="source_type='markdown' cannot have idea_brief or url_source set"
    ):
        run(
            service.create_project(
                title="Conflicting Fields",
                source_type="markdown",
                markdown_source="# Content",
                idea_brief="My idea",
            )
        )


def test_create_project_url_with_idea_brief_raises_value_error(service: ProjectService) -> None:
    with pytest.raises(
        ValueError, match="source_type='url' cannot have idea_brief or markdown_source set"
    ):
        run(
            service.create_project(
                title="Conflicting Fields",
                source_type="url",
                url_source="https://example.com",
                idea_brief="My idea",
            )
        )


def test_create_project_url_with_markdown_source_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(
        ValueError, match="source_type='url' cannot have idea_brief or markdown_source set"
    ):
        run(
            service.create_project(
                title="Conflicting Fields",
                source_type="url",
                url_source="https://example.com",
                markdown_source="# Content",
            )
        )


def test_create_project_with_pasted_json_source_type(service: ProjectService) -> None:
    json_script = '{"scenes": [{"type": "hook", "text": "Hello world"}]}'
    project = run(
        service.create_project(
            title="JSON Project",
            source_type="pasted_json",
            json_script=json_script,
        )
    )

    assert project.title == "JSON Project"
    assert project.source_type == "pasted_json"
    assert project.json_script == json_script
    assert project.idea_brief is None
    assert project.markdown_source is None
    assert project.url_source is None


def test_create_project_pasted_json_missing_script_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(ValueError, match="source_type='pasted_json' requires json_script"):
        run(service.create_project(title="Bad JSON", source_type="pasted_json"))


def test_create_project_pasted_json_with_idea_brief_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(ValueError, match="source_type='pasted_json' cannot have"):
        run(
            service.create_project(
                title="Conflicting",
                source_type="pasted_json",
                json_script='{"scenes": []}',
                idea_brief="Should not be here",
            )
        )


def test_create_project_pasted_json_with_markdown_source_raises_value_error(
    service: ProjectService,
) -> None:
    with pytest.raises(ValueError, match="source_type='pasted_json' cannot have"):
        run(
            service.create_project(
                title="Conflicting",
                source_type="pasted_json",
                json_script='{"scenes": []}',
                markdown_source="# Not allowed",
            )
        )


def test_create_project_idea_with_json_script_raises_value_error(service: ProjectService) -> None:
    with pytest.raises(ValueError, match="source_type='idea' cannot have json_script set"):
        run(
            service.create_project(
                title="Conflicting",
                source_type="idea",
                idea_brief="My idea",
                json_script='{"scenes": []}',
            )
        )


def test_mark_deleting_sets_status(service: ProjectService) -> None:
    created = run(
        service.create_project(
            title="To Delete",
            source_type="idea",
            idea_brief="test",
            workspace_id=1,
        )
    )

    marked = run(service.mark_deleting(created.id, workspace_id=1))

    assert marked.status == "deleting"
    assert marked.id == created.id


def test_mark_deleting_wrong_workspace_raises(service: ProjectService) -> None:
    created = run(
        service.create_project(
            title="To Delete",
            source_type="idea",
            idea_brief="test",
            workspace_id=1,
        )
    )

    with pytest.raises(ValueError, match="not found"):
        run(service.mark_deleting(created.id, workspace_id=999))


def test_mark_deleting_missing_project_raises(service: ProjectService) -> None:
    with pytest.raises(ValueError, match="not found"):
        run(service.mark_deleting(9999, workspace_id=1))


def test_no_inspect_stack_in_project_service() -> None:
    """Verify inspect.stack() brittle enforcement is removed."""
    import creator_service.project_service as mod
    assert not hasattr(mod, '_is_api_context_call'), \
        "_is_api_context_call should be removed from project_service"
    assert not hasattr(mod, '_require_workspace_id_for_api_calls'), \
        "_require_workspace_id_for_api_calls should be removed from project_service"
