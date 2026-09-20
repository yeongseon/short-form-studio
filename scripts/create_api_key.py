#!/usr/bin/env python3
"""Bootstrap script: creates a user, workspace, and API key for local development.

Usage:
    python scripts/create_api_key.py --email local@example.com --workspace local --name local-dev
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import secrets
import sys

# Add packages to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "creator-service"))


async def main(email: str, workspace_name: str, key_name: str) -> None:
    from creator_service.db import get_pool

    pool = await get_pool()

    async with pool.acquire() as conn:
        # 1. Create or get user. Uniqueness is on (auth_provider, auth_subject),
        # not email, so derive a stable auth_subject from the email and upsert
        # on the real constraint.
        auth_subject = email
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, auth_provider, auth_subject)
            VALUES ($1, 'api_key', $2)
            ON CONFLICT ON CONSTRAINT uq_users_auth_provider_auth_subject
            DO UPDATE SET email = EXCLUDED.email
            RETURNING id
            """,
            email,
            auth_subject,
        )
        user_id = row["id"]
        print(f"User: id={user_id} email={email}")

        # 2. Create or get workspace. `slug` is the unique column (not `name`),
        # and `owner_id` is required, so upsert on slug.
        row = await conn.fetchrow(
            """
            INSERT INTO workspaces (name, slug, owner_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
            RETURNING id
            """,
            workspace_name,
            workspace_name,
            user_id,
        )
        workspace_id = row["id"]
        print(f"Workspace: id={workspace_id} name={workspace_name}")

        # 3. Add user to workspace (idempotent)
        await conn.execute(
            "INSERT INTO workspace_members (user_id, workspace_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id,
            workspace_id,
        )
        print(f"Membership: user_id={user_id} workspace_id={workspace_id}")

        # 4. Generate API key
        raw_key = secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        await conn.execute(
            "INSERT INTO api_keys (user_id, key_hash, name) VALUES ($1, $2, $3)",
            user_id,
            key_hash,
            key_name,
        )
        print(f"\n{'='*60}")
        print("API Key (save this — it cannot be recovered):")
        print(f"  {raw_key}")
        print(f"{'='*60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap user, workspace, and API key")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument("--workspace", required=True, help="Workspace name")
    parser.add_argument("--name", required=True, help="API key name/label")
    args = parser.parse_args()

    asyncio.run(main(args.email, args.workspace, args.name))
