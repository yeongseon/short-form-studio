"""Project service with a pluggable async storage backend.

The long-term target is an async DB connection/pool (for example, asyncpg).
Until DB wiring is in place, this module uses an in-memory backend that exposes
the same async service-facing interface.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol


def _load_project_model() -> Any:
    try:
        return importlib.import_module("models").Project
    except ModuleNotFoundError:
        domain_root = Path(__file__).resolve().parents[1] / "creator-domain"
        if str(domain_root) not in sys.path:
            sys.path.insert(0, str(domain_root))
        return importlib.import_module("models").Project


if TYPE_CHECKING:
    from pydantic import BaseModel

    class Project(BaseModel):
        id: int
        title: str | None
        source_type: Literal["idea", "markdown", "url"]
        idea_brief: str | None
        markdown_source: str | None
        url_source: str | None
        status: Literal["draft", "active", "completed", "archived"]
        created_at: datetime
        updated_at: datetime
else:
    Project = _load_project_model()


LatestRunSummary = dict[str, int | str]


class ProjectStorageBackend(Protocol):
    """Abstract async storage interface used by ProjectService."""

    async def insert_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    async def fetch_project(self, project_id: int) -> dict[str, Any] | None:
        ...

    async def list_projects(self, limit: int, offset: int) -> list[dict[str, Any]]:
        ...

    async def fetch_latest_run_summary(self, project_id: int) -> LatestRunSummary | None:
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
            "status": payload.get("status", "draft"),
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

    async def list_projects(self, limit: int, offset: int) -> list[dict[str, Any]]:
        ordered = sorted(
            self._projects.values(),
            key=lambda row: (row["created_at"], row["id"]),
            reverse=True,
        )
        return [dict(row) for row in ordered[offset : offset + limit]]

    async def fetch_latest_run_summary(self, project_id: int) -> LatestRunSummary | None:
        runs = self._runs_by_project.get(project_id, [])
        if not runs:
            return None
        latest = max(runs, key=lambda run: run["id"])
        return {
            "run_id": latest["id"],
            "current_stage": latest["current_stage"],
            "status": latest["status"],
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
    _ALLOWED_SOURCE_TYPES = {"idea", "markdown", "url"}

    def __init__(self, db: ProjectStorageBackend | None = None) -> None:
        self.db = db if db is not None else InMemoryProjectStorage()

    async def create_project(
        self,
        title: str,
        source_type: Literal["idea", "markdown", "url"],
        idea_brief: str | None = None,
        markdown_source: str | None = None,
        url_source: str | None = None,
    ) -> Project:
        if source_type not in self._ALLOWED_SOURCE_TYPES:
            raise ValueError(f"Unsupported source_type '{source_type}'")

        row = await self.db.insert_project(
            {
                "title": title,
                "source_type": source_type,
                "idea_brief": idea_brief,
                "markdown_source": markdown_source,
                "url_source": url_source,
                "status": "draft",
            }
        )
        return Project.model_validate(row)

    async def get_project(self, project_id: int) -> Project | None:
        row = await self.db.fetch_project(project_id)
        if row is None:
            return None

        latest_run = await self.db.fetch_latest_run_summary(project_id)
        return ProjectWithLatestRun.model_validate({**row, "latest_run": latest_run})

    async def list_projects(self, limit: int = 20, offset: int = 0) -> list[Project]:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        if offset < 0:
            raise ValueError("offset must be >= 0")

        rows = await self.db.list_projects(limit=limit, offset=offset)
        projects: list[Project] = []
        for row in rows:
            latest_run = await self.db.fetch_latest_run_summary(row["id"])
            projects.append(ProjectWithLatestRun.model_validate({**row, "latest_run": latest_run}))
        return projects


project_service = ProjectService()
