from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from creator_domain.models import User


class UserStorageBackend(Protocol):
    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    async def get_user(self, user_id: int) -> dict[str, Any] | None: ...

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None: ...

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
        existing = await self.storage.get_user_by_email(email)
        if existing is not None:
            return User.model_validate(existing)

        row = await self.storage.create_user(
            {
                "email": email,
                "name": name,
                "auth_provider": auth_provider,
                "auth_subject": auth_subject,
            }
        )
        return User.model_validate(row)

    async def get_user(self, user_id: int) -> User | None:
        row = await self.storage.get_user(user_id)
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
