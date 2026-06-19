#!/usr/bin/env python3
"""Image generation CLI with experiment mode and metadata tracking.

Usage:
    # Single image with manual prompt
    python gen-image.py "A cat in space"

    # Auto-generate random creative prompt
    python gen-image.py

    # Batch: generate N images with auto-prompts
    python gen-image.py --batch 5

    # EXPERIMENT MODE: same prompt, multiple runs (test randomness)
    python gen-image.py --experiment 4 "A red dragon on a mountain"

    # EXPERIMENT MODE: same prompt, different size hints
    python gen-image.py --experiment-sizes "A serene lake at sunset"

    # Custom output dir
    python gen-image.py --output-dir ./my-images "prompt here"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add project packages to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "creator-provider"))
sys.path.insert(0, str(PROJECT_ROOT / "packages" / "creator-domain"))

from creator_provider.registry import get_default_registry  # noqa: E402

# --- Auto-prompt generation (no LLM needed) ---

SUBJECTS = [
    "a lonely astronaut",
    "a wise old owl",
    "a samurai warrior",
    "a street musician",
    "a robot chef",
    "a mermaid",
    "a time traveler",
    "a ghost in a library",
    "a child discovering magic",
    "twin foxes",
    "a dragon hatchling",
    "a noir detective",
    "a witch's familiar cat",
    "an ancient tree spirit",
    "a cyberpunk hacker",
    "a deep sea diver",
    "a wandering monk",
    "a steampunk inventor",
    "a fairy queen",
    "a lost spaceship",
    "a floating city",
    "a crystal cave",
    "a forgotten temple",
]

SETTINGS = [
    "in a neon-lit Tokyo alley at night",
    "on a cliff overlooking a stormy ocean",
    "in a cozy cabin during a snowstorm",
    "floating among clouds at golden hour",
    "in an abandoned greenhouse overgrown with flowers",
    "on the surface of Mars at dawn",
    "in a crowded night market with paper lanterns",
    "inside a giant clockwork mechanism",
    "at the edge of a glowing forest",
    "in a retro-futuristic space station",
    "on a bridge over a misty valley",
    "in a candlelit underground cathedral",
    "at a crossroads in autumn",
    "inside a snow globe",
    "on a rooftop garden at sunset",
    "in a mirror dimension",
    "beneath a sky full of auroras",
    "at a starlit desert oasis",
]

STYLES = [
    "Studio Ghibli watercolor style",
    "hyperrealistic photography",
    "oil painting, baroque lighting",
    "cyberpunk digital art",
    "minimalist vector illustration",
    "ukiyo-e woodblock print style",
    "pixel art, 16-bit aesthetic",
    "concept art, matte painting",
    "noir graphic novel style",
    "impressionist brushwork",
    "isometric 3D render",
    "vintage film photograph, kodak portra",
    "surrealist dreamscape",
    "art nouveau poster design",
    "pencil sketch with ink wash",
    "vaporwave aesthetic",
    "children's book illustration",
    "photorealistic CGI",
]

MOODS = [
    "serene and contemplative",
    "dramatic and epic",
    "whimsical and playful",
    "melancholic and nostalgic",
    "mysterious and eerie",
    "warm and inviting",
    "dark and foreboding",
    "vibrant and energetic",
    "peaceful and meditative",
    "chaotic and intense",
]

SIZE_HINTS = [None, "1024x1024", "1536x1024", "1024x1536", "512x512", "1792x1024"]


def generate_random_prompt() -> str:
    """Generate a creative prompt by combining random elements."""
    subject = random.choice(SUBJECTS)
    setting = random.choice(SETTINGS)
    style = random.choice(STYLES)
    mood = random.choice(MOODS)
    return f"{subject} {setting}, {mood} mood, {style}, highly detailed"


# --- Gallery metadata ---


def load_gallery(gallery_path: Path) -> list[dict]:
    if gallery_path.exists():
        return json.loads(gallery_path.read_text(encoding="utf-8"))
    return []


def save_gallery(gallery_path: Path, entries: list[dict]) -> None:
    gallery_path.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def add_entry(gallery_path: Path, entry: dict) -> None:
    entries = load_gallery(gallery_path)
    entries.append(entry)
    save_gallery(gallery_path, entries)


# --- Main generation logic ---


async def generate_one(
    prompt: str,
    output_dir: Path,
    gallery_path: Path,
    *,
    index: int | None = None,
    experiment_id: str | None = None,
    experiment_label: str | None = None,
    size_hint: str | None = None,
) -> dict | None:
    registry = get_default_registry()
    provider = registry.get_provider("codex-gpt-image")

    timestamp = datetime.now(timezone.utc).isoformat()
    filename = f"{int(time.time() * 1000)}.png"
    output_path = output_dir / filename

    params: dict = {"output_path": str(output_path)}
    if size_hint:
        params["size"] = size_hint

    start = time.time()
    try:
        result = await provider.generate(prompt, params)
        elapsed = time.time() - start

        entry = {
            "id": int(time.time() * 1000),
            "prompt": prompt,
            "file": filename,
            "path": str(output_path),
            "width": result.width,
            "height": result.height,
            "size_bytes": output_path.stat().st_size,
            "created_at": timestamp,
            "elapsed_seconds": round(elapsed, 1),
            "model": result.model_key,
            "response_id": result.metadata.get("response_id"),
            "revised_prompt": result.metadata.get("revised_prompt"),
        }

        # Experiment tracking
        if experiment_id:
            entry["experiment_id"] = experiment_id
        if experiment_label:
            entry["experiment_label"] = experiment_label
        if size_hint:
            entry["size_hint"] = size_hint

        add_entry(gallery_path, entry)

        prefix = f"[{index}] " if index else ""
        size_mb = entry["size_bytes"] / (1024 * 1024)
        label = f" ({experiment_label})" if experiment_label else ""
        print(
            f"{prefix}✓ {elapsed:.0f}s | {result.width}x{result.height} | "
            f"{size_mb:.1f}MB{label} | {prompt[:50]}..."
        )
        return entry

    except Exception as e:
        elapsed = time.time() - start
        prefix = f"[{index}] " if index else ""
        print(f"{prefix}✗ {elapsed:.0f}s | ERROR: {e}")
        return None


async def run_experiment_repeat(prompt: str, count: int, output_dir: Path, gallery_path: Path):
    """Same prompt, multiple runs — see how results differ."""
    experiment_id = f"exp-repeat-{uuid.uuid4().hex[:8]}"
    print(f"🧪 EXPERIMENT: Same prompt × {count} runs")
    print(f"   ID: {experiment_id}")
    print(f"   Prompt: {prompt[:80]}...")
    print()

    for i in range(1, count + 1):
        await generate_one(
            prompt,
            output_dir,
            gallery_path,
            index=i,
            experiment_id=experiment_id,
            experiment_label=f"run-{i}",
        )


async def run_experiment_sizes(prompt: str, output_dir: Path, gallery_path: Path):
    """Same prompt, different size hints — see what the model does."""
    experiment_id = f"exp-sizes-{uuid.uuid4().hex[:8]}"
    print("🧪 EXPERIMENT: Same prompt × different size hints")
    print(f"   ID: {experiment_id}")
    print(f"   Prompt: {prompt[:80]}...")
    print(f"   Sizes: {[s or 'default(none)' for s in SIZE_HINTS]}")
    print()

    for i, size in enumerate(SIZE_HINTS, 1):
        label = size or "default(none)"
        await generate_one(
            prompt,
            output_dir,
            gallery_path,
            index=i,
            experiment_id=experiment_id,
            experiment_label=f"size={label}",
            size_hint=size,
        )


async def run_experiment_styles(prompt_base: str, output_dir: Path, gallery_path: Path):
    """Same subject, different styles — compare artistic interpretations."""
    experiment_id = f"exp-styles-{uuid.uuid4().hex[:8]}"
    styles_sample = random.sample(STYLES, min(6, len(STYLES)))

    print(f"🧪 EXPERIMENT: Same subject × {len(styles_sample)} styles")
    print(f"   ID: {experiment_id}")
    print(f"   Base: {prompt_base[:60]}...")
    print()

    for i, style in enumerate(styles_sample, 1):
        full_prompt = f"{prompt_base}, {style}, highly detailed"
        await generate_one(
            full_prompt,
            output_dir,
            gallery_path,
            index=i,
            experiment_id=experiment_id,
            experiment_label=style[:30],
        )


async def main():
    parser = argparse.ArgumentParser(
        description="Generate images with experiment mode & metadata tracking"
    )
    parser.add_argument("prompt", nargs="?", help="Image prompt (omit for auto-generate)")
    parser.add_argument("--batch", "-n", type=int, default=1, help="Number of images to generate")
    parser.add_argument(
        "--experiment",
        "-e",
        type=int,
        metavar="N",
        help="Experiment: generate same prompt N times to compare results",
    )
    parser.add_argument(
        "--experiment-sizes",
        action="store_true",
        help="Experiment: try same prompt with different size hints",
    )
    parser.add_argument(
        "--experiment-styles",
        action="store_true",
        help="Experiment: try same subject with different art styles",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=str(PROJECT_ROOT / "data" / "artifacts" / "gallery"),
        help="Output directory",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    gallery_path = output_dir / "gallery.json"

    print(f"📁 Output: {output_dir}")
    print(f"📋 Gallery: {gallery_path}")
    print()

    prompt = args.prompt or generate_random_prompt()
    total_start = time.time()

    # --- Experiment modes ---
    if args.experiment:
        await run_experiment_repeat(prompt, args.experiment, output_dir, gallery_path)
    elif args.experiment_sizes:
        await run_experiment_sizes(prompt, output_dir, gallery_path)
    elif args.experiment_styles:
        await run_experiment_styles(prompt, output_dir, gallery_path)
    # --- Normal mode ---
    else:
        print(f"Generating {args.batch} image(s)...\n")
        success = 0
        for i in range(1, args.batch + 1):
            p = args.prompt if args.prompt else generate_random_prompt()
            result = await generate_one(
                p, output_dir, gallery_path, index=i if args.batch > 1 else None
            )
            if result:
                success += 1
        print(f"\n{'=' * 50}")
        print(f"Done: {success}/{args.batch} succeeded")

    total = time.time() - total_start
    print(f"Total time: {total:.0f}s")
    print(f"Gallery: {len(load_gallery(gallery_path))} entries")


if __name__ == "__main__":
    asyncio.run(main())
