# pyright: reportMissingImports=false

from typing import Any

from creator_provider.exceptions import ProviderTimeoutError, RateLimitError
from tasks.generate_audio import generate_audio
from tasks.generate_paragraph_audio import generate_paragraph_audio
from tasks.generate_paragraph_subtitles import generate_paragraph_subtitles
from tasks.generate_scene_image import generate_scene_image
from tasks import generate_scene_image as generate_scene_image_module
from tasks.generate_script import generate_script
from tasks.generate_subtitles import generate_subtitles
from tasks.generate_visual_plan import generate_visual_plan
from tasks.render_video import render_video


def _assert_common_retry_policy(
    task: Any, *, max_retries: int, soft_time_limit: int, time_limit: int
) -> None:
    assert task.max_retries == max_retries
    autoretry_for = task.autoretry_for
    assert ProviderTimeoutError in autoretry_for
    assert RateLimitError in autoretry_for
    assert task.soft_time_limit == soft_time_limit
    assert task.time_limit == time_limit


def test_task_retry_policies() -> None:
    _assert_common_retry_policy(
        generate_script, max_retries=5, soft_time_limit=300, time_limit=360
    )
    _assert_common_retry_policy(
        generate_audio, max_retries=5, soft_time_limit=300, time_limit=360
    )
    _assert_common_retry_policy(
        generate_subtitles, max_retries=5, soft_time_limit=300, time_limit=360
    )
    _assert_common_retry_policy(
        generate_visual_plan, max_retries=5, soft_time_limit=300, time_limit=360
    )
    _assert_common_retry_policy(
        generate_paragraph_audio, max_retries=3, soft_time_limit=300, time_limit=360
    )
    _assert_common_retry_policy(
        generate_paragraph_subtitles, max_retries=3, soft_time_limit=300, time_limit=360
    )
    _assert_common_retry_policy(
        generate_scene_image, max_retries=5, soft_time_limit=600, time_limit=660
    )
    _assert_common_retry_policy(
        render_video, max_retries=3, soft_time_limit=600, time_limit=660
    )


def test_timeout_bearing_production_tasks_use_parent_visible_claim_request() -> None:
    expected = {
        generate_script: frozenset({"IDEA_READY", "SCRIPT_GENERATING"}),
        generate_audio: frozenset({"VISUAL_ASSET_REVIEW", "AUDIO_GENERATING"}),
        generate_subtitles: frozenset({"AUDIO_GENERATING", "SUBTITLE_GENERATING"}),
        generate_visual_plan: frozenset({"VISUAL_PLAN_GENERATING"}),
        generate_paragraph_audio: frozenset({"AUDIO_GENERATING", "SUBTITLE_GENERATING"}),
        generate_paragraph_subtitles: frozenset({"AUDIO_GENERATING", "SUBTITLE_GENERATING"}),
        generate_scene_image: generate_scene_image_module._SAFE_FAILURE_STAGES,
        render_video: frozenset({"RENDER_GENERATING"}),
    }
    from tasks.hard_timeout import ProductionTask

    for task, safe_failure_stages in expected.items():
        assert isinstance(task, ProductionTask)
        assert task.hard_timeout_safe_failure_stages == safe_failure_stages


def test_production_time_limit_override_is_restricted_to_topology_tests(monkeypatch) -> None:
    from tasks.hard_timeout import production_time_limits

    monkeypatch.setenv("WORKER_TOPOLOGY_PRODUCTION_HARD_TIME_LIMIT", "2")
    assert production_time_limits(600, 660) == (600, 660)

    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("WORKER_TOPOLOGY_PROBE_ENABLED", "1")
    assert production_time_limits(600, 660) == (1, 2)
