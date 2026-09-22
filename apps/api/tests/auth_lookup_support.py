"""SQL-backed auth boundary fixture; records membership query counts."""

import hashlib
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi import Depends, FastAPI
from shorts_api.auth import ApiKeyMiddleware, CurrentUser, get_current_user


class AuthDatabase:
    """Execute the actual lookup SQL against isolated personal-key rows."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            "CREATE TABLE api_keys (id INTEGER PRIMARY KEY, user_id INTEGER, "
            "key_hash TEXT UNIQUE, revoked_at TEXT);"
            "CREATE TABLE workspace_members (user_id INTEGER, workspace_id INTEGER);"
            "INSERT INTO workspace_members VALUES (7, 10), (7, 20), (8, 30);"
        )
        for key_id, user_id, secret, revoked in (
            (71, 7, "personal-one", None),
            (72, 7, "personal-two", None),
            (81, 8, "other-user", None),
            (73, 7, "revoked-key", "2026-01-01"),
            (91, 9, "no-membership", None),
        ):
            self.connection.execute(
                "INSERT INTO api_keys VALUES (?, ?, ?, ?)",
                (key_id, user_id, hashlib.sha256(secret.encode()).hexdigest(), revoked),
            )
        self.membership_calls = 0
        self.fail_duplicate = False
        self.key_error: Exception | None = None
        self.membership_error: Exception | None = None

    async def fetchrow(self, query: str, key_hash: str) -> dict[str, int] | None:
        if self.key_error is not None:
            raise self.key_error
        row = self.connection.execute(query, {"1": key_hash}).fetchone()
        return dict(row) if row is not None else None

    async def fetch(self, query: str, user_id: int) -> list[dict[str, int]]:
        self.membership_calls += 1
        if self.membership_error is not None:
            raise self.membership_error
        if self.fail_duplicate and self.membership_calls > 1:
            raise ConnectionError("duplicate query connection failure")
        return [dict(row) for row in self.connection.execute(query, {"1": user_id})]

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator["AuthDatabase"]:
        yield self


@pytest.fixture
def auth_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[AuthDatabase]:
    database = AuthDatabase()

    async def get_pool() -> AuthDatabase:
        return database

    monkeypatch.setattr("creator_service.db.get_pool", get_pool)
    monkeypatch.setattr("shorts_api.auth.fetch_one", database.fetchrow)
    monkeypatch.setattr("shorts_api.auth.fetch_all", database.fetch)
    try:
        yield database
    finally:
        database.connection.close()


def identity_app(*, middleware: bool = True) -> FastAPI:
    app = FastAPI()
    if middleware:
        app.add_middleware(ApiKeyMiddleware)

    @app.get("/api/creator/identity")
    async def identity(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        return user

    return app
