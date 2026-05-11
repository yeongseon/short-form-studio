#!/usr/bin/env python3
"""Backfill workspace_id on creator_projects with NULL values.

creator_projects has no user_id column, so automated migration cannot determine
the correct workspace. This script provides interactive backfill by:

1. Listing all projects with NULL workspace_id
2. For each project, showing its runs and any associated workspace context
3. Allowing the admin to assign a workspace_id

Usage:
    DATABASE_URL=postgresql://... python scripts/backfill_project_workspace_id.py

Requires: asyncpg (pip install asyncpg)
"""

from __future__ import annotations

import asyncio
import os
import sys


async def main() -> None:
    try:
        import asyncpg
    except ImportError:
        print("Error: asyncpg is required. Install with: pip install asyncpg", file=sys.stderr)
        sys.exit(1)

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable is required", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(database_url)
    try:
        # Find all projects with NULL workspace_id
        orphans = await conn.fetch(
            """
            SELECT p.id, p.title, p.status, p.created_at,
                   COUNT(r.id) AS run_count,
                   array_agg(DISTINCT r.workspace_id) FILTER (WHERE r.workspace_id IS NOT NULL) AS run_workspace_ids
            FROM creator_projects p
            LEFT JOIN creator_runs r ON r.project_id = p.id
            WHERE p.workspace_id IS NULL
            GROUP BY p.id
            ORDER BY p.id
            """
        )

        if not orphans:
            print("No projects with NULL workspace_id found. Nothing to do.")
            return

        print(f"Found {len(orphans)} project(s) with NULL workspace_id:\n")

        # List all workspaces for reference
        workspaces = await conn.fetch("SELECT id, name, slug FROM workspaces ORDER BY id")
        print("Available workspaces:")
        for ws in workspaces:
            print(f"  [{ws['id']}] {ws['name']} ({ws['slug']})")
        print()

        updated = 0
        for row in orphans:
            run_ws_ids = row["run_workspace_ids"]
            suggested = run_ws_ids[0] if run_ws_ids and len(run_ws_ids) == 1 else None

            print(f"Project #{row['id']}: {row['title'] or '(no title)'}")
            print(
                f"  Status: {row['status']}, Created: {row['created_at']}, Runs: {row['run_count']}"
            )
            if run_ws_ids:
                print(f"  Workspace IDs from runs: {run_ws_ids}")
            else:
                print("  No runs with workspace_id found")

            if suggested:
                prompt = (
                    f"  Assign workspace_id [{suggested}] (enter=accept, number=override, s=skip): "
                )
            else:
                prompt = "  Assign workspace_id (number, s=skip): "

            choice = input(prompt).strip()
            if choice.lower() == "s" or choice == "":
                if suggested and choice == "":
                    workspace_id = suggested
                else:
                    print("  Skipped.\n")
                    continue
            else:
                try:
                    workspace_id = int(choice)
                except ValueError:
                    print("  Invalid input, skipped.\n")
                    continue

            await conn.execute(
                "UPDATE creator_projects SET workspace_id = $1 WHERE id = $2 AND workspace_id IS NULL",
                workspace_id,
                row["id"],
            )
            updated += 1
            print(f"  ✓ Updated to workspace_id={workspace_id}\n")

        print(f"Done. Updated {updated}/{len(orphans)} project(s).")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
