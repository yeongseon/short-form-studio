from __future__ import annotations

from typing import Any

from .db import fetch_all, fetch_one


class PostgresUserStorage:
    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        auth_subject = str(payload.get("auth_subject", "")).strip()
        if not auth_subject:
            raise ValueError("auth_subject must not be empty")

        row = await fetch_one(
            """
            INSERT INTO users (email, name, auth_provider, auth_subject)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (auth_provider, auth_subject)
            DO UPDATE SET
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                updated_at = NOW()
            RETURNING *
            """,
            payload.get("email"),
            payload.get("name"),
            payload.get("auth_provider", "api_key"),
            auth_subject,
        )
        if row is None:
            raise ValueError("Failed to create user")
        return row

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        return await fetch_one("SELECT * FROM users WHERE id = $1", user_id)

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return await fetch_one("SELECT * FROM users WHERE email = $1", email)

    async def list_users(self, limit: int, offset: int) -> list[dict[str, Any]]:
        return await fetch_all(
            """
            SELECT *
            FROM users
            ORDER BY created_at DESC, id DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

    async def get_user_by_auth(
        self, auth_provider: str, auth_subject: str
    ) -> dict[str, Any] | None:
        return await fetch_one(
            "SELECT * FROM users WHERE auth_provider = $1 AND auth_subject = $2",
            auth_provider,
            auth_subject,
        )
