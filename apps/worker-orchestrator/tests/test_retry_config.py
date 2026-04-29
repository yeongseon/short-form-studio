# pyright: reportMissingImports=false

from typing import Any

from creator_provider.exceptions import ProviderTimeoutError, RateLimitError
from tasks.generate_audio import generate_audio
from tasks.generate_paragraph_audio import generate_paragraph_audio
from tasks.generate_paragraph_subtitles import generate_paragraph_subtitles
from tasks.generate_scene_image import generate_scene_image
from tasks.generate_script import generate_script
from tasks.generate_subtitles import generate_subtitles
from tasks.generate_visual_plan import generate_visual_plan
from tasks.render_video import render_video


def _assert_common_retry_policy(task: Any, *, soft_time_limit: int, time_limit: int) -> None:
    assert task.max_retries == 3
    autoretry_for = task.autoretry_for
    assert ProviderTimeoutError in autoretry_for
    assert RateLimitError in autoretry_for
    assert task.soft_time_limit == soft_time_limit
    assert task.time_limit == time_limit


def test_task_retry_policies() -> None:
    _assert_common_retry_policy(generate_script, soft_time_limit=300, time_limit=360)
    _assert_common_retry_policy(generate_audio, soft_time_limit=300, time_limit=360)
    _assert_common_retry_policy(generate_subtitles, soft_time_limit=300, time_limit=360)
    _assert_common_retry_policy(generate_visual_plan, soft_time_limit=300, time_limit=360)
    _assert_common_retry_policy(generate_paragraph_audio, soft_time_limit=300, time_limit=360)
    _assert_common_retry_policy(generate_paragraph_subtitles, soft_time_limit=300, time_limit=360)
    _assert_common_retry_policy(generate_scene_image, soft_time_limit=600, time_limit=660)
    _assert_common_retry_policy(render_video, soft_time_limit=600, time_limit=660)
