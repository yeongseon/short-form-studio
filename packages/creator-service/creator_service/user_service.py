from __future__ import annotations

from datetime import datetime, timezone
import re
import secrets
from typing import Any, Protocol

from asyncpg.exceptions import UniqueViolationError
from creator_domain.models import User


class UserStorageBackend(Protocol):
    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def get_user(self, user_id: int) -> dict[str, Any] | None: ...

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None: ...

    async def get_user_by_auth(
        self, auth_provider: str, auth_subject: str
    ) -> dict[str, Any] | None: ...

    async def list_users(self, limit: int, offset: int) -> list[dict[str, Any]]: ...


class InMemoryUserStorage:
    def __init__(self) -> None:
        self._users: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        row = {
            "id": self._next_id,
            "email": payload["email"],
            "name": payload.get("name"),
            "workspace_id": payload.get("workspace_id"),
            "auth_provider": payload.get("auth_provider", "api_key"),
            "auth_subject": payload.get("auth_subject", ""),
            "created_at": now,
            "updated_at": now,
        }
        self._users[self._next_id] = row
        self._next_id += 1
        return dict(row)

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        row = self._users.get(user_id)
        return dict(row) if row is not None else None

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        for row in self._users.values():
            if row["email"] == email:
                return dict(row)
        return None

    async def list_users(self, limit: int, offset: int) -> list[dict[str, Any]]:
        rows = sorted(self._users.values(), key=lambda row: row["id"], reverse=True)
        return [dict(row) for row in rows[offset : offset + limit]]

    async def get_user_by_auth(
        self, auth_provider: str, auth_subject: str
    ) -> dict[str, Any] | None:
        for row in self._users.values():
            if row["auth_provider"] == auth_provider and row["auth_subject"] == auth_subject:
                return dict(row)
        return None


class UserService:
    def __init__(self, storage: UserStorageBackend | None = None) -> None:
        self.storage = storage if storage is not None else InMemoryUserStorage()

    async def create_or_get_user(
        self,
        email: str,
        name: str | None = None,
        auth_provider: str = "api_key",
        auth_subject: str = "",
    ) -> User:
        existing = await self.storage.get_user_by_auth(auth_provider, auth_subject)
        if existing is not None:
            user = User.model_validate(existing)
            return await self._attach_workspace(user)

        row = await self.storage.create_user(
            {
                "email": email,
                "name": name,
                "auth_provider": auth_provider,
                "auth_subject": auth_subject,
            }
        )
        user = User.model_validate(row)
        return await self._attach_workspace(user)

    async def _attach_workspace(self, user: User) -> User:
        from .workspace_service import workspace_service

        user_workspaces = await workspace_service.list_user_workspaces(user.id)
        if user_workspaces:
            user.workspace_id = user_workspaces[0].id
            return user

        slug_base = self._workspace_slug_base(user.email)
        for attempt in range(4):
            slug_candidate = slug_base if attempt == 0 else f"{slug_base}-{secrets.token_hex(2)}"
            try:
                workspace = await workspace_service.create_workspace(
                    name=f"{user.email}'s Workspace",
                    slug=slug_candidate,
                    owner_id=user.id,
                )
            except UniqueViolationError:
                continue

            user.workspace_id = workspace.id
            return user

        raise RuntimeError("Unable to create unique workspace slug after retries")

    def _workspace_slug_base(self, email: str) -> str:
        slug_base = re.sub(r"[^a-z0-9]+", "-", email.strip().lower()).strip("-")
        if not slug_base:
            return "workspace"
        return slug_base

    async def get_user(self, user_id: int) -> User | None:
        row = await self.storage.get_user(user_id)
        if row is None:
            return None
        return User.model_validate(row)

    async def get_user_by_auth(self, auth_provider: str, auth_subject: str) -> User | None:
        row = await self.storage.get_user_by_auth(auth_provider, auth_subject)
        if row is None:
            return None
        return User.model_validate(row)


def _create_storage() -> UserStorageBackend:
    import os

    if os.getenv("DATABASE_URL"):
        from .postgres_user_storage import PostgresUserStorage

        return PostgresUserStorage()
    return InMemoryUserStorage()


user_service = UserService(_create_storage())
