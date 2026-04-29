import asyncio

from creator_service.project_service import InMemoryProjectStorage, ProjectService
from creator_service.run_service import InMemoryRunStorage, RunService


def run(coro):
    return asyncio.run(coro)


def test_project_service_list_projects_can_filter_by_workspace() -> None:
    storage = InMemoryProjectStorage()
    service = ProjectService(storage)

    run(service.create_project(title="A", source_type="idea", idea_brief="a", workspace_id=1))
    run(service.create_project(title="B", source_type="idea", idea_brief="b", workspace_id=2))
    run(service.create_project(title="C", source_type="idea", idea_brief="c", workspace_id=1))

    workspace_projects = run(service.list_projects(workspace_id=1))

    assert len(workspace_projects) == 2
    assert all(project.model_dump().get("workspace_id") == 1 for project in workspace_projects)


def test_run_service_list_runs_by_workspace_filters_rows() -> None:
    storage = InMemoryRunStorage()
    service = RunService(storage)

    first = run(
        storage.create_run(
            {
                "project_id": 1,
                "workspace_id": 10,
                "current_stage": "IDEA_READY",
                "status": "pending",
                "review_stage": None,
                "restart_from": None,
                "model_defaults_json": None,
                "metadata_json": None,
                "style_preset": "default",
                "started_at": None,
                "finished_at": None,
            }
        )
    )
    run(
        storage.create_run(
            {
                "project_id": 2,
                "workspace_id": 20,
                "current_stage": "IDEA_READY",
                "status": "pending",
                "review_stage": None,
                "restart_from": None,
                "model_defaults_json": None,
                "metadata_json": None,
                "style_preset": "default",
                "started_at": None,
                "finished_at": None,
            }
        )
    )

    rows = run(service.list_runs_by_workspace(10))

    assert len(rows) == 1
    assert rows[0].id == first["id"]
