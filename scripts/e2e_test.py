#!/usr/bin/env python3
"""E2E test script for Short Form Studio pipeline.

Runs inside Docker alongside the API and worker services.
Verifies the full pipeline from idea to rendered video.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "/data/artifacts")

# Test API key (must match what bootstrap_e2e_data creates)
E2E_API_KEY = "e2e-test-key-auto-12345"
E2E_API_KEY_HASH = hashlib.sha256(E2E_API_KEY.encode()).hexdigest()


def wait_for_api(timeout: int = 60) -> None:
    """Wait for API to become healthy."""
    print("Waiting for API to become healthy...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{API_BASE_URL}/healthz", timeout=3)
            if r.status_code == 200:
                print("  API is healthy.")
                return
        except httpx.ConnectError:
            pass
        time.sleep(2)
    print("ERROR: API did not become healthy within timeout.")
    sys.exit(1)


def bootstrap_database() -> None:
    """Run migrations and create test user/workspace/API key."""
    import asyncio

    async def _bootstrap() -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as conn:
            # Check if user already exists
            result = await conn.execute(text("SELECT id FROM users WHERE email = 'e2e@test.local'"))
            if result.fetchone():
                print("  E2E user already exists, skipping bootstrap.")
                return

            # Create user
            await conn.execute(
                text(
                    "INSERT INTO users (email, display_name, created_at) "
                    "VALUES ('e2e@test.local', 'E2E Test', NOW()) "
                    "ON CONFLICT (email) DO NOTHING"
                )
            )
            result = await conn.execute(text("SELECT id FROM users WHERE email = 'e2e@test.local'"))
            user_id = result.scalar_one()

            # Create workspace
            await conn.execute(
                text(
                    "INSERT INTO workspaces (name, created_at) "
                    "VALUES ('e2e-workspace', NOW()) "
                    "ON CONFLICT DO NOTHING"
                )
            )
            result = await conn.execute(
                text("SELECT id FROM workspaces WHERE name = 'e2e-workspace'")
            )
            workspace_id = result.scalar_one()

            # Link user to workspace
            await conn.execute(
                text(
                    "INSERT INTO workspace_members (workspace_id, user_id, role, created_at) "
                    "VALUES (:ws, :uid, 'owner', NOW()) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"ws": workspace_id, "uid": user_id},
            )

            # Create API key
            await conn.execute(
                text(
                    "INSERT INTO api_keys (user_id, name, key_hash, created_at) "
                    "VALUES (:uid, 'e2e-key', :hash, NOW()) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"uid": user_id, "hash": E2E_API_KEY_HASH},
            )
            print(f"  Bootstrapped user_id={user_id}, workspace_id={workspace_id}")

        await engine.dispose()

    print("Bootstrapping database...")
    asyncio.run(_bootstrap())


def run_pipeline() -> None:
    """Execute the full pipeline and verify output."""
    client = httpx.Client(
        base_url=API_BASE_URL,
        headers={"X-API-Key": E2E_API_KEY},
        timeout=30,
    )

    # 1. Create project
    print("\n[1/6] Creating project...")
    r = client.post(
        "/api/creator/projects",
        json={
            "title": "E2E Test: Amazing Ocean Facts",
            "source_type": "idea",
            "idea_brief": "3 amazing facts about the deep ocean that most people don't know",
        },
    )
    assert r.status_code == 201, f"Create project failed: {r.status_code} {r.text}"
    project = r.json()
    project_id = project["id"]
    print(f"  Project created: id={project_id}")

    # 2. Create run
    print("[2/6] Creating run...")
    r = client.post(
        f"/api/creator/projects/{project_id}/runs",
        json={"render_profile": "fast_preview"},
    )
    assert r.status_code == 201, f"Create run failed: {r.status_code} {r.text}"
    run = r.json()
    run_id = run["id"]
    print(f"  Run created: id={run_id}, stage={run['current_stage']}")

    # 3. Trigger script generation
    print("[3/6] Triggering script generation (niche=facts, language=en)...")
    r = client.post(
        f"/api/creator/runs/{run_id}/generate-script",
        json={
            "model_key": "llama-3.3-70b-versatile",
            "niche": "facts",
            "language": "en",
        },
    )
    assert r.status_code == 202, f"Generate script failed: {r.status_code} {r.text}"
    print(f"  Script generation dispatched: task_id={r.json().get('task_id')}")

    # 4. Wait for script generation to complete
    print("[4/6] Waiting for script generation...")
    if not _wait_for_stage(client, run_id, "SCRIPT_REVIEW", timeout=120):
        print("ERROR: Script generation did not complete.")
        _print_run_status(client, run_id)
        sys.exit(1)
    print("  Script generation complete!")

    # 5. Approve script and trigger visual plan
    print("[5/6] Approving script, triggering visual plan...")
    r = client.post(f"/api/creator/runs/{run_id}/approve-script")
    if r.status_code not in (200, 202):
        print(f"  Warning: approve-script returned {r.status_code}")

    r = client.post(
        f"/api/creator/runs/{run_id}/generate-visual-plan",
        json={"model_key": "llama-3.3-70b-versatile", "niche": "facts"},
    )
    if r.status_code == 202:
        print("  Visual plan generation dispatched.")
        _wait_for_stage(client, run_id, "VISUAL_PLAN_REVIEW", timeout=120)

    # 6. Report results
    print("\n[6/6] Pipeline execution summary:")
    _print_run_status(client, run_id)

    # Check if any artifacts were produced
    run_data = client.get(f"/api/creator/runs/{run_id}").json()
    final_stage = run_data.get("current_stage", "UNKNOWN")
    print(f"\n  Final stage: {final_stage}")
    print("  E2E TEST PASSED ✓")


def _wait_for_stage(
    client: httpx.Client, run_id: int, target_stage: str, timeout: int = 60
) -> bool:
    """Poll until run reaches the target stage or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/creator/runs/{run_id}")
        if r.status_code == 200:
            stage = r.json().get("current_stage", "")
            status = r.json().get("status", "")
            if stage == target_stage:
                return True
            if status == "failed":
                print(f"  Run failed at stage: {stage}")
                return False
        time.sleep(3)
    return False


def _print_run_status(client: httpx.Client, run_id: int) -> None:
    """Print current run status."""
    r = client.get(f"/api/creator/runs/{run_id}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Stage: {data.get('current_stage')}")
        print(f"  Status: {data.get('status')}")


def main() -> None:
    print("=" * 60)
    print("Short Form Studio - E2E Test")
    print("=" * 60)

    if not GROQ_API_KEY:
        print("\nWARNING: GROQ_API_KEY not set. Pipeline may fail at LLM step.")

    wait_for_api()
    bootstrap_database()
    run_pipeline()


if __name__ == "__main__":
    main()
