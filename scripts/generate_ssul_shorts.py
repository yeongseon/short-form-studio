#!/usr/bin/env python3
"""Generate a 썰쇼츠-style video directly (text-on-black, narration, BGM, styled subtitles).

This mimics the style of Korean storytelling YouTube Shorts:
- Black background with large white Korean text
- Emotional narration (Edge-TTS)
- Ambient BGM mixed underneath
- ASS subtitles at the bottom

Usage:
    python3 scripts/generate_ssul_shorts.py [output_dir]
"""

import asyncio
import subprocess
import sys
from pathlib import Path

# Add packages to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages/creator-service"))
sys.path.insert(0, str(ROOT / "packages/creator-provider"))
sys.path.insert(0, str(ROOT / "packages/creator-domain"))

OUTPUT_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/ssul_output"

# --- 썰 스토리 (감성 가족 이야기) ---
STORY_LINES = [
    "아빠가 마지막으로 내게 한 말.",
    '"미안하다, 아들아.\n더 잘해주지 못해서."',
    "그날 아빠는\n처음으로 눈물을 보였다.",
    "나는 아무 말도\n할 수 없었다.",
    "20년이 지나서야\n그 말의 무게를 알았다.",
    "아빠의 사랑은\n말이 아닌 희생이었다.",
    "당신의 아버지에게\n오늘 전화 한 통 하세요.",
]


async def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    scenes_dir = OUTPUT_DIR / "scenes"
    scenes_dir.mkdir(exist_ok=True)

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🎬 썰쇼츠 생성 시작")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 1. 텍스트 씬 이미지 생성
    print("\n📝 [1/5] 텍스트 씬 이미지 생성...")
    from creator_service.text_scene_renderer import render_text_scene

    scene_paths = []
    for i, line in enumerate(STORY_LINES):
        path = scenes_dir / f"scene_{i:03d}.png"
        render_text_scene(line, path, font_size=80)
        scene_paths.append(path)
        print(f"  ✓ Scene {i + 1}: {line[:20]}...")

    # 2. TTS 나레이션 생성
    print("\n🔊 [2/5] 한국어 TTS 나레이션 생성...")
    full_narration = " ".join(line.replace("\n", " ") for line in STORY_LINES)
    audio_path = OUTPUT_DIR / "narration.mp3"

    try:
        import edge_tts

        voice = "ko-KR-InJoonNeural"  # 남성 감성 목소리
        communicate = edge_tts.Communicate(full_narration, voice, rate="-10%")
        await communicate.save(str(audio_path))
        print(f"  ✓ 나레이션 저장: {audio_path} ({audio_path.stat().st_size / 1024:.1f}KB)")
    except Exception as e:
        print(f"  ⚠ Edge-TTS 실패: {e}")
        # 무음 오디오 생성 (fallback)
        duration = len(STORY_LINES) * 4
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r=24000:cl=mono",
                "-t",
                str(duration),
                str(audio_path),
            ],
            capture_output=True,
        )
        print(f"  ✓ 무음 fallback 생성 ({duration}s)")

    # 3. 오디오 길이 확인 및 씬 duration 계산
    print("\n⏱ [3/5] 씬 타이밍 계산...")
    probe_result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    total_duration = float(probe_result.stdout.strip())
    scene_duration = total_duration / len(STORY_LINES)
    scene_durations = [scene_duration] * len(STORY_LINES)
    print(f"  ✓ 총 {total_duration:.1f}s / {len(STORY_LINES)} 씬 = {scene_duration:.1f}s/씬")

    # 4. SRT 자막 생성 + ASS 변환
    print("\n📝 [4/5] 자막 생성 (SRT → ASS)...")
    srt_path = OUTPUT_DIR / "subtitles.srt"
    ass_path = OUTPUT_DIR / "subtitles.ass"

    srt_content = ""
    current_time = 0.0
    for i, line in enumerate(STORY_LINES):
        start = current_time
        end = current_time + scene_duration
        srt_content += f"{i + 1}\n"
        srt_content += f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
        srt_content += f"{line.replace(chr(10), ' ')}\n\n"
        current_time = end

    srt_path.write_text(srt_content, encoding="utf-8")

    from creator_service.ffmpeg_service import FFmpegService

    ffmpeg = FFmpegService()
    ffmpeg.convert_srt_to_ass(str(srt_path), str(ass_path))
    print(f"  ✓ ASS 자막 생성: {ass_path}")

    # 5. BGM 생성 + 믹싱
    print("\n🎵 [5/5] BGM 생성 + 오디오 믹싱...")
    bgm_path = OUTPUT_DIR / "bgm.mp3"
    mixed_path = OUTPUT_DIR / "audio_mixed.mp3"

    from creator_service.bgm_service import bgm_service

    bgm_service.generate_ambient_bgm(total_duration, str(bgm_path), mood="emotional")
    bgm_service.mix_audio_with_bgm(str(audio_path), str(bgm_path), str(mixed_path))
    print(f"  ✓ BGM 믹싱 완료: {mixed_path}")

    # 6. FFmpeg 영상 렌더링
    print("\n🎥 렌더링...")
    from creator_service.ffmpeg_service import RenderInput

    output_mp4 = OUTPUT_DIR / "output.mp4"
    render_input = RenderInput(
        image_paths=[p for p in scene_paths],
        audio_path=mixed_path,
        subtitle_path=ass_path,
        scene_durations=scene_durations,
    )
    ffmpeg.render(render_input, output_mp4)

    size_mb = output_mp4.stat().st_size / (1024 * 1024)
    print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"🎉 썰쇼츠 완성!")
    print(f"  📹 {output_mp4}")
    print(f"  📦 {size_mb:.2f} MB")
    print(f"  ⏱ {total_duration:.1f}초")
    print(f"  🖼 {len(scene_paths)} 씬 (검은배경 + 흰 텍스트)")
    print(f"  🔊 한국어 TTS + BGM")
    print(f"  📝 ASS 스타일 자막")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")


def _format_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int((s - int(s)) * 1000)
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


if __name__ == "__main__":
    asyncio.run(main())
