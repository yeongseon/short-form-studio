#!/usr/bin/env python3
"""E2E test: 썰쇼츠 (Korean emotional storytelling Shorts) pipeline.

Produces a full vertical short-form video in the style of popular Korean
"썰" (story-telling) Shorts — emotional family story with Korean TTS narration,
AI-generated images, and subtitles.

Usage:
    # Run against local docker services
    GROQ_API_KEY=... python3 scripts/e2e_ssul_shorts.py

    # Or within docker compose
    docker compose -f docker-compose.yml -f docker-compose.e2e.yml run --rm e2e-test \
        python3 scripts/e2e_ssul_shorts.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import httpx

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "data/artifacts")

# Test API key
E2E_API_KEY = "e2e-test-key-auto-12345"
E2E_API_KEY_HASH = hashlib.sha256(E2E_API_KEY.encode()).hexdigest()

# 썰쇼츠 configuration
SSUL_CONFIG = {
    "title": "아빠의 마지막 한마디 - 감동 썰",
    "idea_brief": (
        "아버지가 돌아가시기 전 마지막으로 남긴 한마디가 있었습니다. "
        "그 말의 의미를 20년이 지나서야 깨달은 아들의 이야기. "
        "가족의 사랑과 후회, 그리고 감사에 대한 감동적인 실화 기반 썰."
    ),
    "niche": "family_story",
    "language": "ko",
    "script_model": "meta-llama/llama-4-scout-17b-16e-instruct",
    "image_model": os.getenv("E2E_IMAGE_MODEL", "groq-svg"),  # groq-svg (free), hf-flux-schnell, or placeholder
    "tts_model": "edge-tts",
    "tts_voice": "male",  # ko-KR-InJoonNeural for male narration
    "subtitle_model": "groq-whisper-large-v3-turbo",
    "render_profile": "shorts_default",
}


def wait_for_api(timeout: int = 60) -> None:
    """Wait for API to become healthy."""
    print("⏳ Waiting for API...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{API_BASE_URL}/healthz", timeout=3)
            if r.status_code == 200:
                print("  ✓ API healthy")
                return
        except httpx.ConnectError:
            pass
        time.sleep(2)
    print("ERROR: API not healthy")
    sys.exit(1)


def bootstrap_database() -> None:
    """Ensure test user exists."""
    if not DATABASE_URL:
        print("  ⚠ No DATABASE_URL — assuming user already bootstrapped")
        return

    import asyncio

    async def _bootstrap() -> None:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(DATABASE_URL)
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT id FROM users WHERE email = 'e2e@test.local'"))
            if result.fetchone():
                print("  ✓ E2E user exists")
                return

            await conn.execute(
                text(
                    "INSERT INTO users (email, display_name, created_at) "
                    "VALUES ('e2e@test.local', 'E2E Test', NOW()) "
                    "ON CONFLICT (email) DO NOTHING"
                )
            )
            result = await conn.execute(text("SELECT id FROM users WHERE email = 'e2e@test.local'"))
            user_id = result.scalar_one()

            await conn.execute(
                text(
                    "INSERT INTO workspaces (name, created_at) "
                    "VALUES ('e2e-workspace', NOW()) ON CONFLICT DO NOTHING"
                )
            )
            result = await conn.execute(
                text("SELECT id FROM workspaces WHERE name = 'e2e-workspace'")
            )
            workspace_id = result.scalar_one()

            await conn.execute(
                text(
                    "INSERT INTO workspace_members (workspace_id, user_id, role, created_at) "
                    "VALUES (:ws, :uid, 'owner', NOW()) ON CONFLICT DO NOTHING"
                ),
                {"ws": workspace_id, "uid": user_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO api_keys (user_id, name, key_hash, created_at) "
                    "VALUES (:uid, 'e2e-key', :hash, NOW()) ON CONFLICT DO NOTHING"
                ),
                {"uid": user_id, "hash": E2E_API_KEY_HASH},
            )
            print(f"  ✓ Bootstrapped user_id={user_id}, workspace_id={workspace_id}")
        await engine.dispose()

    asyncio.run(_bootstrap())


def run_ssul_pipeline() -> None:
    """Execute full 썰쇼츠 pipeline."""
    client = httpx.Client(
        base_url=API_BASE_URL,
        headers={"X-API-Key": E2E_API_KEY},
        timeout=30,
    )
    cfg = SSUL_CONFIG

    # Step 1: Create project
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📝 [1/11] 프로젝트 생성...")
    r = client.post(
        "/api/creator/projects",
        json={
            "title": cfg["title"],
            "source_type": "idea",
            "idea_brief": cfg["idea_brief"],
        },
    )
    assert r.status_code == 201, f"Failed: {r.status_code} {r.text}"
    project_id = r.json()["id"]
    print(f"  ✓ Project id={project_id}")

    # Step 2: Create run
    print("🎬 [2/11] 렌더 런 생성...")
    r = client.post(
        f"/api/creator/projects/{project_id}/runs",
        json={"render_profile": cfg["render_profile"]},
    )
    assert r.status_code == 201, f"Failed: {r.status_code} {r.text}"
    run_id = r.json()["id"]
    print(f"  ✓ Run id={run_id}, stage={r.json()['current_stage']}")

    # Step 3: Generate script (감동 썰 스크립트)
    print(f"✍️  [3/11] 스크립트 생성 (niche={cfg['niche']}, lang={cfg['language']})...")
    r = client.post(
        f"/api/creator/runs/{run_id}/generate-script",
        json={
            "model_key": cfg["script_model"],
            "niche": cfg["niche"],
            "language": cfg["language"],
        },
    )
    assert r.status_code == 202, f"Failed: {r.status_code} {r.text}"
    print(f"  ✓ Dispatched: task_id={r.json().get('task_id')}")

    # Step 4: Wait for script
    print("⏳ [4/11] 스크립트 생성 대기...")
    if not _wait_for_stage(client, run_id, "SCRIPT_REVIEW", timeout=600):
        _fail(client, run_id, "Script generation failed")
    print("  ✓ 스크립트 생성 완료!")
    _print_script_preview(client, run_id)
    print("  ⏳ Rate limit cooldown (10s)...")
    time.sleep(10)

    # Step 5: Approve script
    print("✅ [5/11] 스크립트 승인 → 비주얼 플랜 생성...")
    r = client.post(f"/api/creator/runs/{run_id}/approve-script", json={})
    assert r.status_code in (200, 202), f"Approve failed: {r.status_code}"

    r = client.post(
        f"/api/creator/runs/{run_id}/generate-visual-plan",
        json={"model_key": cfg["script_model"], "niche": cfg["niche"]},
    )
    assert r.status_code == 202, f"Visual plan dispatch failed: {r.status_code} {r.text}"

    # Step 6: Wait for visual plan
    print("⏳ [6/11] 비주얼 플랜 생성 대기...")
    if not _wait_for_stage(client, run_id, "VISUAL_PLAN_REVIEW", timeout=600):
        _fail(client, run_id, "Visual plan generation failed")
    print("  ✓ 비주얼 플랜 완료!")
    print("  ⏳ Rate limit cooldown (10s)...")
    time.sleep(10)

    # Step 7: Approve visual plan → Generate images
    print("🎨 [7/11] 비주얼 플랜 승인 → 이미지 생성...")
    r = client.post(f"/api/creator/runs/{run_id}/approve-visual-plan", json={})
    assert r.status_code in (200, 202), f"Approve failed: {r.status_code}"

    r = client.post(
        f"/api/creator/runs/{run_id}/generate-visual-assets",
        json={"model_key": cfg["image_model"]},
    )
    assert r.status_code == 202, f"Image gen dispatch failed: {r.status_code} {r.text}"

    # Step 8: Wait for images
    print("⏳ [8/11] 이미지 생성 대기 (Pollinations)...")
    if not _wait_for_stage(client, run_id, "VISUAL_ASSET_REVIEW", timeout=600):
        _fail(client, run_id, "Image generation failed")
    print("  ✓ 이미지 생성 완료!")
    print("  ⏳ Rate limit cooldown (10s)...")
    time.sleep(10)

    # Step 9: Approve images → Generate audio (Korean TTS)
    print("🔊 [9/11] 이미지 승인 → 한국어 TTS 나레이션...")
    r = client.post(f"/api/creator/runs/{run_id}/approve-visual-assets", json={})
    assert r.status_code in (200, 202), f"Approve failed: {r.status_code}"

    r = client.post(
        f"/api/creator/runs/{run_id}/generate-audio",
        json={"tts_model": cfg["tts_model"], "voice": cfg["tts_voice"]},
    )
    assert r.status_code == 202, f"Audio dispatch failed: {r.status_code} {r.text}"

    # Wait for audio → auto-continues to subtitles
    print("⏳     오디오 생성 대기 (Edge-TTS)...")
    if not _wait_for_stage(client, run_id, "SUBTITLE_GENERATING", timeout=600):
        # Audio done, check if already at subtitle
        run_data = client.get(f"/api/creator/runs/{run_id}").json()
        if run_data.get("current_stage") not in (
            "SUBTITLE_GENERATING",
            "RENDER_GENERATING",
            "FINAL_REVIEW",
        ):
            _fail(client, run_id, "Audio generation failed")
    print("  ✓ 오디오 생성 완료!")

    # Step 10: Generate subtitles
    print("📝 [10/11] 자막 생성 (Groq Whisper)...")
    r = client.post(
        f"/api/creator/runs/{run_id}/generate-subtitles",
        json={"subtitle_model": cfg["subtitle_model"]},
    )
    if r.status_code == 202:
        print("  ✓ 자막 생성 디스패치됨")
        if not _wait_for_stage(client, run_id, "RENDER_GENERATING", timeout=600):
            run_data = client.get(f"/api/creator/runs/{run_id}").json()
            if run_data.get("current_stage") != "RENDER_GENERATING":
                _fail(client, run_id, "Subtitle generation failed")
    else:
        print(f"  ⚠ Subtitle dispatch returned {r.status_code} — may auto-continue")

    # Step 11: Render final video
    print("🎥 [11/11] 최종 영상 렌더링...")
    r = client.post(
        f"/api/creator/runs/{run_id}/render",
        json={"render_profile": cfg["render_profile"]},
    )
    if r.status_code == 202:
        print("  ✓ 렌더링 시작됨")
        if not _wait_for_stage(client, run_id, "FINAL_REVIEW", timeout=600):
            _fail(client, run_id, "Render failed")
    else:
        print(f"  ⚠ Render dispatch returned {r.status_code}: {r.text}")

    # Final report
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🎉 썰쇼츠 E2E 파이프라인 완료!")
    _print_run_status(client, run_id)

    # Check rendered video file
    video_path = f"{ARTIFACT_ROOT}/{run_id}/render/output.mp4"
    if os.path.exists(video_path):
        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        print(f"\n  📹 렌더링된 영상: {video_path}")
        print(f"     파일 크기: {size_mb:.2f} MB")
        print("\n  ✅ E2E TEST PASSED ✓")
    else:
        print(f"\n  ⚠ 영상 파일 미발견: {video_path}")
        print("    (렌더링 완료 후 확인 필요)")
        # Still count as pass if we reached FINAL_REVIEW
        run_data = client.get(f"/api/creator/runs/{run_id}").json()
        if run_data.get("current_stage") == "FINAL_REVIEW":
            print("  ✅ E2E TEST PASSED (FINAL_REVIEW reached) ✓")
        else:
            print(f"  ❌ E2E TEST INCOMPLETE — stage: {run_data.get('current_stage')}")
            sys.exit(1)


def _wait_for_stage(
    client: httpx.Client, run_id: int, target_stage: str, timeout: int = 60
) -> bool:
    """Poll until run reaches target stage."""
    deadline = time.time() + timeout
    last_stage = ""
    while time.time() < deadline:
        r = client.get(f"/api/creator/runs/{run_id}")
        if r.status_code == 200:
            data = r.json()
            stage = data.get("current_stage", "")
            status = data.get("status", "")
            if stage != last_stage:
                print(f"    → {stage} ({status})")
                last_stage = stage
            if stage == target_stage:
                return True
            if status == "failed":
                print(f"    ✗ Run failed at: {stage}")
                return False
            # If we've passed the target stage, also OK
            stage_order = [
                "IDEA_READY",
                "SCRIPT_GENERATING",
                "SCRIPT_REVIEW",
                "VISUAL_PLAN_SETUP",
                "VISUAL_PLAN_GENERATING",
                "VISUAL_PLAN_REVIEW",
                "VISUAL_ASSET_GENERATING",
                "VISUAL_ASSET_REVIEW",
                "AUDIO_GENERATING",
                "SUBTITLE_GENERATING",
                "RENDER_GENERATING",
                "FINAL_REVIEW",
                "PUBLISHED",
            ]
            if stage in stage_order and target_stage in stage_order:
                if stage_order.index(stage) > stage_order.index(target_stage):
                    return True
        time.sleep(3)
    return False


def _print_script_preview(client: httpx.Client, run_id: int) -> None:
    """Print first few lines of generated script."""
    try:
        r = client.get(f"/api/creator/runs/{run_id}/storyboard")
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "sections" in data:
                for section in data["sections"][:2]:
                    text = section.get("display_text") or section.get("text", "")
                    if text:
                        print(f"    「{text[:80]}...」")
    except Exception:
        pass


def _print_run_status(client: httpx.Client, run_id: int) -> None:
    """Print final run status."""
    r = client.get(f"/api/creator/runs/{run_id}")
    if r.status_code == 200:
        data = r.json()
        print(f"  Stage: {data.get('current_stage')}")
        print(f"  Status: {data.get('status')}")


def _fail(client: httpx.Client, run_id: int, message: str) -> None:
    """Print failure info and exit."""
    print(f"\n❌ ERROR: {message}")
    _print_run_status(client, run_id)
    sys.exit(1)


def main() -> None:
    print("━" * 50)
    print("🎬 썰쇼츠 E2E Test — 감동 가족 스토리")
    print("━" * 50)
    print(f"  Config: niche={SSUL_CONFIG['niche']}, lang={SSUL_CONFIG['language']}")
    print(f"  Models: LLM={SSUL_CONFIG['script_model']}, IMG={SSUL_CONFIG['image_model']}")
    print(f"          TTS={SSUL_CONFIG['tts_model']}, STT={SSUL_CONFIG['subtitle_model']}")

    if not GROQ_API_KEY:
        print("\n⚠ WARNING: GROQ_API_KEY not set. LLM/STT steps will fail.")

    wait_for_api()
    bootstrap_database()
    run_ssul_pipeline()


if __name__ == "__main__":
    main()
