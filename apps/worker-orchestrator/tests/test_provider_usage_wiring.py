from __future__ import annotations

import inspect
from typing import Any

from tasks import (
    generate_audio,
    generate_paragraph_audio,
    generate_paragraph_subtitles,
    generate_scene_image,
    generate_script,
    generate_subtitles,
    generate_visual_plan,
    render_video,
)


def _source(module: Any) -> str:
    return inspect.getsource(module)


def test_provider_usage_wiring_present_in_worker_tasks() -> None:
    expected = {
        generate_script: ["record_provider_call(", "entry.provider_type", "model_key", '"llm"'],
        generate_visual_plan: [
            "record_provider_call(",
            "entry.provider_type",
            "model_key",
            '"llm"',
        ],
        generate_audio: ["record_provider_call(", "entry.provider_type", "tts_model", '"tts"'],
        generate_paragraph_audio: [
            "record_provider_call(",
            "entry.provider_type",
            "tts_model",
            '"tts"',
        ],
        generate_subtitles: [
            "record_provider_call(",
            "entry.provider_type",
            "subtitle_model",
            '"stt"',
        ],
        generate_paragraph_subtitles: [
            "record_provider_call(",
            "entry.provider_type",
            "subtitle_model",
            '"stt"',
        ],
        generate_scene_image: [
            "record_provider_call(",
            "entry.provider_type",
            "model_key",
            '"image_gen"',
        ],
        render_video: ["record_provider_call(", '"ffmpeg"', "render_profile", '"render"'],
    }

    for module, tokens in expected.items():
        source = _source(module)
        assert "from creator_service.usage_service import record_provider_call" in source
        for token in tokens:
            assert token in source
        assert 'logger.warning("Failed to record provider usage", exc_info=True)' in source
