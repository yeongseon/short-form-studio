#!/usr/bin/env python3
"""E2E test: Create a project and run the full pipeline with free providers.

Uses:
- LLM: Groq (llama-3.3-70b-versatile)
- Image: Pollinations.ai (pollinations)
- TTS: Edge TTS (edge-tts)
- STT: Groq Whisper (groq-whisper-large-v3-turbo)
"""

from __future__ import annotations

import json
import sys
import time

import httpx

BASE_URL = "http://127.0.0.1:8000"
API_KEY = "e2e-test-key-12345"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# Free provider model keys
LLM_MODEL = "llama-3.3-70b-versatile"
IMAGE_MODEL = "placeholder"
TTS_MODEL = "edge-tts"
STT_MODEL = "groq-whisper-large-v3-turbo"


def api(method: str, path: str, json_data: dict | None = None, timeout: float = 30.0) -> dict:
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(method, f"{BASE_URL}{path}", headers=HEADERS, json=json_data)
        print(f"  {method} {path} -> {resp.status_code}")
        if resp.status_code >= 400:
            print(f"    ERROR: {resp.text[:500]}")
            sys.exit(1)
        return resp.json() if resp.content else {}


def wait_for_stage(run_id: int, target_stage: str, max_wait: int = 180) -> dict:
    """Poll run until it reaches target_stage or FAILED."""
    start = time.time()
    while time.time() - start < max_wait:
        run = api("GET", f"/api/creator/runs/{run_id}")
        stage = run.get("current_stage", "")
        status = run.get("status", "")
        if stage == target_stage:
            return run
        if stage == "FAILED" or status == "failed":
            print(f"    RUN FAILED at stage={stage}")
            sys.exit(1)
        time.sleep(3)
    print(f"    TIMEOUT waiting for stage={target_stage} (stuck at {stage})")
    sys.exit(1)


def main():
    print("\n=== E2E Test: Free Provider Pipeline ===\n")

    # 1. Create project
    print("[1] Create project")
    project = api(
        "POST",
        "/api/creator/projects",
        {
            "title": "E2E Test - AI Shorts",
            "source_type": "idea",
            "idea_brief": "Create a 15-second short video about the joy of morning coffee. 2 scenes. Keep the script under 30 words. English only.",
        },
    )
    project_id = project["id"]
    print(f"    Project created: id={project_id}")

    # 2. Create run with free provider defaults
    print("[2] Create run")
    run = api(
        "POST",
        f"/api/creator/projects/{project_id}/runs",
        {},
    )
    run_id = run["id"]
    print(f"    Run created: id={run_id}, stage={run.get('current_stage')}")

    # 3. Generate script
    print("[3] Generate script (Groq LLM)")
    api(
        "POST",
        f"/api/creator/runs/{run_id}/generate-script",
        {
            "model_key": LLM_MODEL,
        },
        timeout=60,
    )
    run = wait_for_stage(run_id, "SCRIPT_REVIEW", max_wait=120)
    print(f"    Script generated! Stage: {run['current_stage']}")

    # 4. Approve script
    print("[4] Approve script")
    api(
        "POST",
        f"/api/creator/runs/{run_id}/approve-script",
        {
            "reviewer": "e2e-bot",
        },
    )

    # 5. Generate visual plan
    print("[5] Generate visual plan (Groq LLM)")
    run = api("GET", f"/api/creator/runs/{run_id}")
    if run["current_stage"] == "VISUAL_PLAN_SETUP":
        api(
            "POST",
            f"/api/creator/runs/{run_id}/generate-visual-plan",
            {
                "model_key": LLM_MODEL,
            },
            timeout=60,
        )
    run = wait_for_stage(run_id, "VISUAL_PLAN_REVIEW", max_wait=120)
    print(f"    Visual plan generated! Stage: {run['current_stage']}")

    # 6. Approve visual plan
    print("[6] Approve visual plan")
    api(
        "POST",
        f"/api/creator/runs/{run_id}/approve-visual-plan",
        {
            "reviewer": "e2e-bot",
        },
    )

    # 7. Generate images (placeholder)
    print("[7] Generate images (placeholder)")
    run = api("GET", f"/api/creator/runs/{run_id}")
    if run["current_stage"] == "VISUAL_ASSET_GENERATING":
        api(
            "POST",
            f"/api/creator/runs/{run_id}/generate-visual-assets",
            {"model_key": IMAGE_MODEL},
            timeout=60,
        )
    run = wait_for_stage(run_id, "VISUAL_ASSET_REVIEW", max_wait=300)
    print(f"    Images generated! Stage: {run['current_stage']}")

    # 8. Approve images
    print("[8] Approve visual assets")
    api(
        "POST",
        f"/api/creator/runs/{run_id}/approve-visual-assets",
        {
            "reviewer": "e2e-bot",
        },
    )

    # 9. Generate audio (Edge TTS)
    print("[9] Generate audio (Edge TTS)")
    api(
        "POST",
        f"/api/creator/runs/{run_id}/generate-audio",
        {"tts_model": TTS_MODEL},
        timeout=120,
    )
    run = wait_for_stage(run_id, "SUBTITLE_GENERATING", max_wait=180)
    print(f"    Audio generated! Stage: {run['current_stage']}")

    # 10. Generate subtitles (Groq Whisper)
    print("[10] Generate subtitles (Groq Whisper)")
    api(
        "POST",
        f"/api/creator/runs/{run_id}/generate-subtitles",
        {"subtitle_model": STT_MODEL},
        timeout=120,
    )
    run = wait_for_stage(run_id, "RENDER_GENERATING", max_wait=180)
    print(f"    Subtitles generated! Stage: {run['current_stage']}")

    # 11. Render video
    print("[11] Render video")
    api(
        "POST",
        f"/api/creator/runs/{run_id}/render",
        {"render_profile": "shorts_default"},
        timeout=120,
    )
    run = wait_for_stage(run_id, "FINAL_REVIEW", max_wait=300)
    print(f"    Video rendered! Stage: {run['current_stage']}")

    # 12. Approve final
    print("[12] Approve final")
    api(
        "POST",
        f"/api/creator/runs/{run_id}/approve-final",
        {
            "reviewer": "e2e-bot",
        },
    )
    run = api("GET", f"/api/creator/runs/{run_id}")
    print(f"    Final stage: {run['current_stage']}, status: {run.get('status')}")

    print("\n=== E2E TEST PASSED ===")
    print(f"Pipeline completed: project_id={project_id}, run_id={run_id}")
    print(f"Final stage: {run['current_stage']}")


if __name__ == "__main__":
    main()
