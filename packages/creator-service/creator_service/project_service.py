"""Project service with a pluggable async storage backend.

The long-term target is an async DB connection/pool (for example, asyncpg).
Until DB wiring is in place, this module uses an in-memory backend that exposes
the same async service-facing interface.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from creator_domain.models.project import Project

import creator_service.run_service as _run_svc_mod

LatestRunSummary = dict[str, int | str | None]


class ProjectStorageBackend(Protocol):
    """Abstract async storage interface used by ProjectService."""

    async def insert_project(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def fetch_project(self, project_id: int) -> dict[str, Any] | None: ...

    async def list_projects(
        self, limit: int, offset: int, workspace_id: int | None = None
    ) -> list[dict[str, Any]]: ...

    async def fetch_latest_run_summary(self, project_id: int) -> LatestRunSummary | None: ...

    async def count_projects(self) -> int: ...

    async def update_project(
        self, project_id: int, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update project fields. Returns updated row or None if not found."""
        ...

    async def delete_project(self, project_id: int) -> bool:
        """Delete a project by id. Returns True if deleted."""
        ...


class InMemoryProjectStorage:
    """Temporary async storage backend used before DB integration."""

    def __init__(self) -> None:
        self._projects: dict[int, dict[str, Any]] = {}
        self._runs_by_project: dict[int, list[dict[str, Any]]] = {}
        self._next_project_id = 1
        self._next_run_id = 1

    async def insert_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        project_id = self._next_project_id
        self._next_project_id += 1

        row = {
            "id": project_id,
            "title": payload.get("title"),
            "source_type": payload.get("source_type", "idea"),
            "idea_brief": payload.get("idea_brief"),
            "markdown_source": payload.get("markdown_source"),
            "url_source": payload.get("url_source"),
            "json_script": payload.get("json_script"),
            "status": payload.get("status", "draft"),
            "workspace_id": payload.get("workspace_id"),
            "created_at": now,
            "updated_at": now,
        }
        self._projects[project_id] = row
        return dict(row)

    async def fetch_project(self, project_id: int) -> dict[str, Any] | None:
        row = self._projects.get(project_id)
        if row is None:
            return None
        return dict(row)

    async def list_projects(
        self, limit: int, offset: int, workspace_id: int | None = None
    ) -> list[dict[str, Any]]:
        ordered = sorted(
            self._projects.values(),
            key=lambda row: (row["created_at"], row["id"]),
            reverse=True,
        )
        if workspace_id is not None:
            ordered = [row for row in ordered if row.get("workspace_id") == workspace_id]
        return [dict(row) for row in ordered[offset : offset + limit]]

    async def count_projects(self) -> int:
        return len(self._projects)

    async def update_project(
        self, project_id: int, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self._projects.get(project_id)
        if row is None:
            return None
        for key, value in updates.items():
            row[key] = value
        row["updated_at"] = datetime.now(timezone.utc)
        return dict(row)

    async def delete_project(self, project_id: int) -> bool:
        if project_id in self._projects:
            del self._projects[project_id]
            # Also remove associated runs
            self._runs_by_project.pop(project_id, None)
            return True
        return False

    async def fetch_latest_run_summary(self, project_id: int) -> LatestRunSummary | None:
        runs = self._runs_by_project.get(project_id, [])
        if runs:
            latest = max(runs, key=lambda run: run["id"])
            return {
                "run_id": latest["id"],
                "current_stage": latest["current_stage"],
                "status": latest["status"],
            }

        # In real local/dev flow, runs are created through RunService, not via
        # this storage's insert_run helper.  Fall back to the shared in-memory
        # run service so latest_run stays accurate outside Postgres mode.
        try:
            persisted_runs = await _run_svc_mod.run_service.list_runs_by_project(project_id)
        except Exception:
            return None
        if not persisted_runs:
            return None
        latest_run = persisted_runs[0]
        return {
            "run_id": latest_run.id,
            "current_stage": latest_run.current_stage,
            "status": latest_run.status,
        }

    async def insert_run(
        self,
        project_id: int,
        current_stage: str | None,
        status: str,
    ) -> dict[str, Any]:
        run_id = self._next_run_id
        self._next_run_id += 1
        row = {
            "id": run_id,
            "project_id": project_id,
            "current_stage": current_stage,
            "status": status,
            "created_at": datetime.now(timezone.utc),
        }
        self._runs_by_project.setdefault(project_id, []).append(row)
        return dict(row)


class ProjectWithLatestRun(Project):
    latest_run: LatestRunSummary | None = None


class ProjectService:
    _ALLOWED_SOURCE_TYPES = {"idea", "markdown", "url", "pasted_json"}

    def __init__(self, db: ProjectStorageBackend | None = None) -> None:
        self.db = db if db is not None else InMemoryProjectStorage()

    async def create_project(
        self,
        title: str,
        source_type: Literal["idea", "markdown", "url", "pasted_json"],
        idea_brief: str | None = None,
        markdown_source: str | None = None,
        url_source: str | None = None,
        json_script: str | None = None,
        workspace_id: int | None = None,
    ) -> Project:
        if source_type not in self._ALLOWED_SOURCE_TYPES:
            raise ValueError(f"Unsupported source_type '{source_type}'")

        # Validate payload matches source_type
        if source_type == "markdown" and markdown_source is None:
            raise ValueError("source_type='markdown' requires markdown_source to be provided")
        if source_type == "url" and url_source is None:
            raise ValueError("source_type='url' requires url_source to be provided")
        if source_type == "idea" and idea_brief is None:
            raise ValueError("source_type='idea' requires idea_brief to be provided")

        # Enforce field exclusivity: each source_type should only have its corresponding field
        if source_type == "idea" and (markdown_source is not None or url_source is not None):
            raise ValueError("source_type='idea' cannot have markdown_source or url_source set")
        if source_type == "markdown" and (idea_brief is not None or url_source is not None):
            raise ValueError("source_type='markdown' cannot have idea_brief or url_source set")
        if source_type == "url" and (idea_brief is not None or markdown_source is not None):
            raise ValueError("source_type='url' cannot have idea_brief or markdown_source set")

        if source_type == "pasted_json" and json_script is None:
            raise ValueError("source_type='pasted_json' requires json_script to be provided")
        if source_type == "pasted_json" and (
            idea_brief is not None or markdown_source is not None or url_source is not None
        ):
            raise ValueError(
                "source_type='pasted_json' cannot have idea_brief, markdown_source, or url_source set"
            )
        if source_type != "pasted_json" and json_script is not None:
            raise ValueError(f"source_type='{source_type}' cannot have json_script set")

        row = await self.db.insert_project(
            {
                "title": title,
                "source_type": source_type,
                "idea_brief": idea_brief,
                "markdown_source": markdown_source,
                "url_source": url_source,
                "json_script": json_script,
                "status": "draft",
                "workspace_id": workspace_id,
            }
        )
        return Project.model_validate(row)

    async def get_project(self, project_id: int) -> Project | None:
        row = await self.db.fetch_project(project_id)
        if row is None:
            return None

        latest_run = await self.db.fetch_latest_run_summary(project_id)
        return ProjectWithLatestRun.model_validate({**row, "latest_run": latest_run})

    async def list_projects(
        self, limit: int = 20, offset: int = 0, workspace_id: int | None = None
    ) -> list[Project]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        rows = await self.db.list_projects(limit=limit, offset=offset, workspace_id=workspace_id)
        projects: list[Project] = []
        for row in rows:
            latest_run = await self.db.fetch_latest_run_summary(row["id"])
            projects.append(ProjectWithLatestRun.model_validate({**row, "latest_run": latest_run}))
        return projects

    async def count_projects(self) -> int:
        return await self.db.count_projects()

    async def update_project(self, project_id: int, title: str) -> Project | None:
        """Update project title."""
        row = await self.db.update_project(project_id, {"title": title})
        if row is None:
            return None
        latest_run = await self.db.fetch_latest_run_summary(project_id)
        return ProjectWithLatestRun.model_validate({**row, "latest_run": latest_run})

    async def delete_project(self, project_id: int) -> bool:
        """Delete a project. FK cascade handles associated runs."""
        return await self.db.delete_project(project_id)


def _create_storage() -> ProjectStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_project_storage import PostgresProjectStorage

        return PostgresProjectStorage()
    return InMemoryProjectStorage()


project_service = ProjectService(_create_storage())
