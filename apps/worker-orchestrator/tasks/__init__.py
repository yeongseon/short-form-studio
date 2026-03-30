"""Task modules for worker orchestration."""

# Import all task modules for auto-discovery
from . import (
    generate_audio,
    generate_scene_image,
    generate_script,
    generate_subtitles,
    generate_visual_plan,
    render_video,
)

__all__ = [
    "generate_script",
    "generate_visual_plan",
    "generate_scene_image",
    "generate_audio",
    "generate_subtitles",
    "render_video",
]
