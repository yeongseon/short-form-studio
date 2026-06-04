"""Render text-based scene images for 썰쇼츠 (Korean storytelling Shorts).

Produces 1080x1920 (9:16) images with:
- Black background
- Large white Korean text centered
- Optional gradient overlay for visual interest
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_WIDTH = 1080
_HEIGHT = 1920
_BG_COLOR = (10, 10, 10)  # near-black
_TEXT_COLOR = (255, 255, 255)
_FONT_SIZE = 72
_LINE_SPACING = 24
_MARGIN_X = 100  # horizontal padding

# Korean-capable fonts in priority order
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load first available Korean font."""
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap_text(text: str, max_chars_per_line: int = 16) -> list[str]:
    """Wrap Korean text into short lines for visual impact."""
    lines = []
    for paragraph in text.split("\n"):
        wrapped = textwrap.wrap(paragraph, width=max_chars_per_line)
        lines.extend(wrapped if wrapped else [""])
    return lines


def render_text_scene(
    text: str,
    output_path: str | Path,
    *,
    font_size: int = _FONT_SIZE,
    bg_color: tuple[int, int, int] = _BG_COLOR,
    text_color: tuple[int, int, int] = _TEXT_COLOR,
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> Path:
    """Render a single text scene image.

    Args:
        text: The text to display (Korean or any language).
        output_path: Where to save the PNG.
        font_size: Font size in pixels.
        bg_color: Background RGB color.
        text_color: Text RGB color.
        width: Image width.
        height: Image height.

    Returns:
        Path to the saved image.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    font = _load_font(font_size)

    lines = _wrap_text(text)

    # Calculate total text block height
    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])

    total_height = sum(line_heights) + _LINE_SPACING * (len(lines) - 1)
    y = (height - total_height) // 2

    # Draw each line centered
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = (width - line_width) // 2
        draw.text((x, y), line, fill=text_color, font=font)
        y += line_heights[i] + _LINE_SPACING

    img.save(str(output_path), "PNG")
    return output_path


def render_scenes_from_subtitles(
    srt_path: str | Path,
    output_dir: str | Path,
    *,
    font_size: int = _FONT_SIZE,
) -> list[Path]:
    """Parse SRT and render one image per subtitle entry.

    Each subtitle cue becomes a scene with its text displayed as the visual.
    Returns list of image paths in order.
    """
    srt_path = Path(srt_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = _parse_srt(srt_path.read_text(encoding="utf-8"))
    paths = []
    for i, entry in enumerate(entries):
        img_path = output_dir / f"scene_{i:03d}.png"
        render_text_scene(entry["text"], img_path, font_size=font_size)
        paths.append(img_path)
    return paths


def _parse_srt(content: str) -> list[dict]:
    """Parse SRT content into list of {start, end, text} dicts."""
    entries = []
    blocks = content.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        # line 0 = index, line 1 = timestamps, line 2+ = text
        time_line = lines[1]
        text = "\n".join(lines[2:])
        parts = time_line.split(" --> ")
        if len(parts) == 2:
            entries.append(
                {
                    "start": _srt_time_to_seconds(parts[0].strip()),
                    "end": _srt_time_to_seconds(parts[1].strip()),
                    "text": text,
                }
            )
    return entries


def _srt_time_to_seconds(time_str: str) -> float:
    """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
    time_str = time_str.replace(",", ".")
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    return 0.0
