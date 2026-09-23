"""Exercise section fallback through the real Celery task and common runner."""

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from celery.exceptions import SoftTimeLimitExceeded as CelerySoftTimeLimitExceeded
from creator_domain.models.script_draft import ScriptSection
from creator_service.audio_service import AudioService, InMemoryAudioStorage
from creator_service.script_service import InMemoryScriptStorage, ScriptService
from tasks import generate_audio as audio
from worker_loop import run_in_worker_loop

from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import RunnerCase, runner_case as runner_case


@dataclass(frozen=True, slots=True)
class AudioCase:
    runner: RunnerCase
    provider: AsyncMock
    artifacts: AudioService
    root: Path
    usage: AsyncMock


@pytest.fixture
def audio_case(
    runner_case: RunnerCase, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> AudioCase:
    run_in_worker_loop(runner_case.runs.storage.update_run(
        runner_case.run_id, {"current_stage": "AUDIO_GENERATING"},
    ))
    scripts = ScriptService(InMemoryScriptStorage())
    run_in_worker_loop(scripts.save_draft(
        runner_case.run_id, "pasted_json", markdown_content="Opening. Ending.",
        structured_script=[
            ScriptSection(section_id="opening", type="hook", text="Opening."),
            ScriptSection(section_id="ending", type="conclusion", text="Ending."),
        ],
    ))
    artifacts = AudioService(InMemoryAudioStorage())
    provider = AsyncMock()
    entry = SimpleNamespace(
        requires_gpu=False, provider_type="edge_tts", default_params={}, endpoint="offline",
    )
    registry = SimpleNamespace(
        resolve=Mock(return_value=entry), get_provider=Mock(return_value=provider),
    )
    usage = AsyncMock()
    monkeypatch.setattr(audio, "_script_service", scripts)
    monkeypatch.setattr(audio, "_audio_service", artifacts)
    monkeypatch.setattr(audio, "get_default_registry", lambda: registry)
    monkeypatch.setattr(audio, "record_provider_call", usage)
    monkeypatch.setattr(audio, "_ARTIFACT_ROOT", str(tmp_path))
    return AudioCase(runner_case, provider, artifacts, tmp_path, usage)


def test_soft_timeout_escapes_section_without_fallback(audio_case: AudioCase) -> None:
    # Given the actual billiard exception on the first section, then a viable fallback.
    case = audio_case
    timeout = SoftTimeLimitExceeded()
    assert SoftTimeLimitExceeded is CelerySoftTimeLimitExceeded
    case.provider.generate.side_effect = [timeout, None]
    audio.generate_audio.push_request(id="audio-timeout", retries=0, args=(), kwargs={})
    try:
        # When the real task/runner executes the section.
        with pytest.raises(SoftTimeLimitExceeded) as raised:
            audio.generate_audio.run(case.runner.run_id, tts_model="edge-tts")
    finally:
        audio.generate_audio.pop_request()
    # Then the same timeout escapes without another provider call or persisted output.
    assert raised.value is timeout
    case.provider.generate.assert_awaited_once()
    case.usage.assert_not_awaited()
    assert run_in_worker_loop(case.artifacts.storage.list_by_run(case.runner.run_id)) == []
    assert run_in_worker_loop(case.artifacts.storage.list_by_run_sections(case.runner.run_id)) == []
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["current_stage"], saved["status"]) == ("FAILED", "failed")


@pytest.mark.parametrize("error", [
    RuntimeError("section unavailable"),
])
def test_ordinary_section_error_keeps_legacy_single_pass_fallback(
    audio_case: AudioCase, error: Exception,
) -> None:
    # Given a section error followed by a successful single-pass provider result.
    case = audio_case
    case.provider.generate.side_effect = [error, None]
    output = case.root / str(case.runner.run_id) / "audio" / "audio.mp3"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"offline audio" * 100)
    # When the real task executes normally.
    result = audio.generate_audio.apply(
        args=(case.runner.run_id,), kwargs={"tts_model": "edge-tts"},
        task_id="audio-fallback", throw=True,
    )
    # Then the legacy fallback succeeds and finalizes both task and run.
    assert result.state == "SUCCESS"
    assert case.provider.generate.await_count == 2
    section_call, fallback_call = case.provider.generate.await_args_list
    assert section_call.args == ("Opening.",)
    assert fallback_call.args == ("Opening. Ending.",)
    assert Path(section_call.kwargs["params"]["output_path"]).name == "section_0.mp3"
    assert Path(fallback_call.kwargs["params"]["output_path"]).name == "audio.mp3"
    tracked = run_in_worker_loop(case.runner.tracking.list_run_tasks(case.runner.run_id))
    assert [task.status for task in tracked] == ["success"]
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["current_stage"], saved["status"]) == ("SUBTITLE_GENERATING", "running")


@pytest.mark.parametrize("stage,status", [
    ("AUDIO_GENERATING", "cancelled"), ("SUBTITLE_GENERATING", "running"),
])
def test_section_timeout_preserves_concurrent_run_state(
    audio_case: AudioCase, stage: str, status: str,
) -> None:
    # Given a cancellation or stage advance during the first provider call.
    case = audio_case

    async def interrupt(*_args: str, **_kwargs: str) -> None:
        await case.runner.runs.storage.update_run(
            case.runner.run_id, {"current_stage": stage, "status": status},
        )
        raise SoftTimeLimitExceeded()

    case.provider.generate.side_effect = interrupt
    # When the actual runner receives the timeout.
    with pytest.raises(SoftTimeLimitExceeded):
        audio.generate_audio.run(case.runner.run_id, tts_model="edge-tts")
    # Then no fallback runs and the caller's conditional failure policy is preserved.
    case.provider.generate.assert_awaited_once()
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["current_stage"], saved["status"]) == (stage, status)


def test_celery_marks_section_timeout_delivery_failed(
    audio_case: AudioCase, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a soft timeout with retry budget available and an offline DLQ boundary.
    case = audio_case
    case.provider.generate.side_effect = [SoftTimeLimitExceeded(), None]
    dlq = Mock()
    monkeypatch.setattr("celery_app._record_failed_task_to_dlq", dlq)
    # When Celery's actual trace processes the exception (not just task.run).
    result = audio.generate_audio.apply(
        args=(case.runner.run_id,), kwargs={"tts_model": "edge-tts"},
        task_id="audio-celery-timeout", throw=False,
    )
    # Then this is a failed delivery, not success or a provider retry.
    assert result.state == "FAILURE"
    assert isinstance(result.result, SoftTimeLimitExceeded)
    case.provider.generate.assert_awaited_once()
    dlq.assert_called_once()
    assert isinstance(dlq.call_args.kwargs["exception"], SoftTimeLimitExceeded)
