from unittest.mock import patch

import pytest

from creator_service.task_dispatch_service import TaskDispatchService


@pytest.mark.parametrize(("method", "arguments", "task", "args", "kwargs"), [
    ("dispatch_generate_script", (7, "idea", "llm", None), "generate_script", [],
     {"run_id": 7, "idea_brief": "idea", "model_key": "llm", "instructions": None, "niche": None, "language": "ko"}),
    ("dispatch_generate_visual_plan", (7, "llm", "style"), "generate_visual_plan", [],
     {"run_id": 7, "model_key": "llm", "style_preset": "style", "niche": None}),
    ("dispatch_generate_audio", (7, "tts", "voice"), "generate_audio", [7],
     {"tts_model": "tts", "voice": "voice"}),
    ("dispatch_generate_subtitles", (7, "stt", "srt"), "generate_subtitles", [7],
     {"subtitle_model": "stt", "subtitle_format": "srt"}),
    ("dispatch_render_video", (7, "vertical"), "render_video", [7], {"render_profile": "vertical"}),
    ("dispatch_generate_scene_image", (7, "image", "scene", "prompt", False, {"steps": 4}),
     "generate_scene_image", [7], {"scene_id": "scene", "model_key": "image", "prompt_override": "prompt", "is_active": False, "image_params": {"steps": 4}}),
    ("dispatch_paragraph_audio", (7, "section", "tts", "voice"), "generate_paragraph_audio", [7],
     {"section_id": "section", "tts_model": "tts", "voice": "voice"}),
    ("dispatch_paragraph_subtitles", (7, "section", "stt", "srt"), "generate_paragraph_subtitles", [7],
     {"section_id": "section", "subtitle_model": "stt", "subtitle_format": "srt"}),
])
def test_wrappers_preserve_worker_call_contract(method, arguments, task, args, kwargs) -> None:
    service = TaskDispatchService()
    with patch.object(service, "_dispatch_task", return_value="chosen-id") as dispatch:
        result = getattr(service, method)(*arguments, task_id="chosen-id")
    assert result == "chosen-id"
    assert dispatch.call_count == 1
    request = dispatch.call_args.kwargs
    assert request["task_attr"] == task
    assert request["run_id"] == 7
    assert request.get("args", []) == args
    assert request["kwargs"] == kwargs
    assert request["task_id"] == "chosen-id"
