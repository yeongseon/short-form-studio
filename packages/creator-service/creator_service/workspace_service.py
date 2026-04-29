from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models import Workspace, WorkspaceMember


class WorkspaceStorageBackend(Protocol):
    async def create_workspace(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def get_workspace(self, workspace_id: int) -> dict[str, Any] | None: ...

    async def get_workspace_by_slug(self, slug: str) -> dict[str, Any] | None: ...

    async def list_user_workspaces(self, user_id: int) -> list[dict[str, Any]]: ...

    async def add_member(
        self, workspace_id: int, user_id: int, role: str = "member"
    ) -> dict[str, Any]: ...

    async def remove_member(self, workspace_id: int, user_id: int) -> bool: ...

    async def check_membership(self, workspace_id: int, user_id: int) -> bool: ...


class InMemoryWorkspaceStorage:
    def __init__(self) -> None:
        self._workspaces: dict[int, dict[str, Any]] = {}
        self._memberships: dict[tuple[int, int], dict[str, Any]] = {}
        self._next_id = 1

    async def create_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        row = {
            "id": self._next_id,
            "name": payload["name"],
            "slug": payload["slug"],
            "owner_id": payload["owner_id"],
            "created_at": now,
            "updated_at": now,
        }
        self._workspaces[self._next_id] = row
        self._next_id += 1
        return dict(row)

    async def get_workspace(self, workspace_id: int) -> dict[str, Any] | None:
        row = self._workspaces.get(workspace_id)
        return dict(row) if row is not None else None

    async def get_workspace_by_slug(self, slug: str) -> dict[str, Any] | None:
        for row in self._workspaces.values():
            if row["slug"] == slug:
                return dict(row)
        return None

    async def list_user_workspaces(self, user_id: int) -> list[dict[str, Any]]:
        workspace_ids = {wid for (wid, uid), _ in self._memberships.items() if uid == user_id}
        rows = [row for wid, row in self._workspaces.items() if wid in workspace_ids]
        rows.sort(key=lambda row: row["id"], reverse=True)
        return [dict(row) for row in rows]

    async def add_member(
        self, workspace_id: int, user_id: int, role: str = "member"
    ) -> dict[str, Any]:
        row = {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "role": role,
            "joined_at": datetime.now(timezone.utc),
        }
        self._memberships[(workspace_id, user_id)] = row
        return dict(row)

    async def remove_member(self, workspace_id: int, user_id: int) -> bool:
        key = (workspace_id, user_id)
        if key not in self._memberships:
            return False
        del self._memberships[key]
        return True

    async def check_membership(self, workspace_id: int, user_id: int) -> bool:
        return (workspace_id, user_id) in self._memberships


class WorkspaceService:
    def __init__(self, storage: WorkspaceStorageBackend | None = None) -> None:
        self.storage = storage if storage is not None else InMemoryWorkspaceStorage()

    async def create_workspace(self, name: str, slug: str, owner_id: int) -> Workspace:
        row = await self.storage.create_workspace(
            {
                "name": name,
                "slug": slug,
                "owner_id": owner_id,
            }
        )
        await self.storage.add_member(row["id"], owner_id, role="owner")
        return Workspace.model_validate(row)

    async def get_workspace(self, workspace_id: int) -> Workspace | None:
        row = await self.storage.get_workspace(workspace_id)
        if row is None:
            return None
        return Workspace.model_validate(row)

    async def list_user_workspaces(self, user_id: int) -> list[Workspace]:
        rows = await self.storage.list_user_workspaces(user_id)
        return [Workspace.model_validate(row) for row in rows]

    async def add_member(
        self, workspace_id: int, user_id: int, role: str = "member"
    ) -> WorkspaceMember:
        row = await self.storage.add_member(workspace_id, user_id, role=role)
        return WorkspaceMember.model_validate(row)

    async def check_access(self, workspace_id: int, user_id: int) -> bool:
        return await self.storage.check_membership(workspace_id, user_id)


def _create_storage() -> WorkspaceStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_workspace_storage import PostgresWorkspaceStorage

        return PostgresWorkspaceStorage()
    return InMemoryWorkspaceStorage()


workspace_service = WorkspaceService(_create_storage())
