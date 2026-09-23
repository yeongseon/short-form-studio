from unittest.mock import AsyncMock

import pytest
from creator_provider.exceptions import ProviderError, ProviderTimeoutError, RateLimitError
from creator_service.script_service import ScriptService
from tasks.task_execution import TaskInputError
from worker_loop import run_in_worker_loop

from .provider_boundary_support import GenerationCase, generation_case as generation_case
from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import runner_case as runner_case


@pytest.mark.parametrize("error_type,message,translated", [
    (RuntimeError, "unexpected failure", ProviderError),
    (ValueError, "invalid output", ProviderError),
    (TimeoutError, "timeout", ProviderTimeoutError),
    (ConnectionError, "offline", ProviderTimeoutError),
    (RuntimeError, "429 too many requests", RateLimitError),
])
def test_nonprovider_errors_keep_translation(
    generation_case: GenerationCase, monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception], message: str, translated: type[ProviderError],
) -> None:
    case = generation_case
    monkeypatch.setattr("tasks.scene_batch_lifecycle.SceneBatch.backoff", AsyncMock())
    error = error_type(message)
    case.provider.generate.side_effect = error
    case.provider.transcribe.side_effect = error
    case.task.push_request(id="ordinary-error", args=case.args, kwargs={}, retries=case.task.max_retries)
    try:
        if case.task.name == "generate_scene_image" and translated is ProviderError:
            result = case.task.run(*case.args)
            assert result["status"] == "failed"
            assert result["failed"] == 2
            assert len(result["scene_results"]) == 2
        else:
            with pytest.raises(translated) as raised:
                case.task.run(*case.args)
            assert type(raised.value) is translated
            assert raised.value.__cause__ is error
    finally:
        case.task.pop_request()


@pytest.mark.parametrize("generation_case", [
    ("generate_script", "SCRIPT_GENERATING", ("An offline idea",)),
], indirect=True)
def test_normal_script_still_saves_and_advances(generation_case: GenerationCase) -> None:
    case = generation_case
    result = case.task.apply(args=case.args, task_id="normal-script", throw=True)
    assert result.state == "SUCCESS"
    draft = run_in_worker_loop(case.scripts.get_active_draft(case.runner.run_id))
    assert draft is not None and "offline generated script" in draft.markdown_content
    assert draft.source_type == "generated_by_model"
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["current_stage"], saved["status"]) == ("SCRIPT_REVIEW", "paused")
    case.provider.generate.assert_awaited_once()


@pytest.mark.parametrize("generation_case", [
    ("generate_audio", "AUDIO_GENERATING", ()),
    ("generate_paragraph_audio", "AUDIO_GENERATING", ("sec-1",)),
    ("generate_visual_plan", "VISUAL_PLAN_GENERATING", ()),
    ("generate_subtitles", "SUBTITLE_GENERATING", ()),
], indirect=True)
def test_task_input_rejection_keeps_run_editable(
    generation_case: GenerationCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = generation_case
    monkeypatch.setattr(case.module, "_script_service", ScriptService())
    with pytest.raises(TaskInputError):
        case.task.run(*case.args)
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["current_stage"], saved["status"]) == (case.stage, "running")
    case.provider.generate.assert_not_awaited()
    case.provider.transcribe.assert_not_awaited()
