from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from tasks import generate_script as generate_script_module


@dataclass
class FakeEntry:
    provider_type: str = "ollama"
    endpoint: str = "http://ollama:11434"
    requires_gpu: bool = True
    default_params: dict[str, object] | None = None


class FakeProvider:
    def __init__(self, result: str = "Generated script", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    async def generate(self, prompt: str, params: dict[str, object] | None = None) -> str:
        self.calls.append((prompt, params))
        if self.error is not None:
            raise self.error
        return self.result


class FakeStorage:
    def __init__(
        self,
        error: Exception | None = None,
        runs: dict[int, dict[str, object]] | None = None,
    ) -> None:
        self.error = error
        self.calls: list[tuple[int, dict[str, object]]] = []
        self._runs: dict[int, dict[str, object]] = runs or {}

    async def get_run(self, run_id: int) -> dict[str, object] | None:
        return self._runs.get(run_id)

    async def update_run(self, run_id: int, updates: dict[str, object]) -> dict[str, object]:
        self.calls.append((run_id, updates))
        if self.error is not None:
            raise self.error
        return {"id": run_id, **updates}

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        expected_stages: frozenset[str],
    rejected_statuses: frozenset[str] | None = None,
    ) -> tuple[bool, dict[str, object] | None]:
        row = self._runs.get(run_id)
        if row is None:
            return False, None
        if row.get("current_stage") not in expected_stages:
            return False, dict(row)
        self.calls.append((run_id, updates))
        if self.error is not None:
            raise self.error
        row.update(updates)
        self._runs[run_id] = row
        return True, dict(row)


def _make_storage(run_id: int = 101, stage: str = "IDEA_READY", **extra: Any) -> FakeStorage:
    """Create a FakeStorage pre-populated with a single run in the given stage."""
    run_row: dict[str, object] = {"id": run_id, "current_stage": stage, **extra}
    return FakeStorage(runs={run_id: run_row})


class FakeScriptService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, str, str | None]] = []

    async def save_draft(
        self,
        run_id: int,
        source_type: str,
        markdown_content: str | None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        self.calls.append((run_id, source_type, markdown_content))
        if self.error is not None:
            raise self.error
        return {"run_id": run_id, "source_type": source_type, "markdown_content": markdown_content}


class FakeRegistry:
    def __init__(
        self, entry: FakeEntry, provider: FakeProvider, resolve_error: Exception | None = None
    ) -> None:
        self.entry = entry
        self.provider = provider
        self.resolve_error = resolve_error

    def resolve(self, _model_key: str) -> FakeEntry:
        if self.resolve_error is not None:
            raise self.resolve_error
        return self.entry

    def get_provider(self, _model_key: str) -> FakeProvider:
        return self.provider


def _patch_registry(monkeypatch: pytest.MonkeyPatch, registry: FakeRegistry) -> None:
    monkeypatch.setattr(generate_script_module, "get_default_registry", lambda: registry)


def _patch_redis(monkeypatch: pytest.MonkeyPatch, redis_client: object) -> None:
    redis_stub = SimpleNamespace(Redis=SimpleNamespace(from_url=lambda _: redis_client))
    monkeypatch.setattr("tasks.task_runner.redis", redis_stub)


def _patch_services(
    monkeypatch: pytest.MonkeyPatch,
    script_service: FakeScriptService,
    storage: FakeStorage,
) -> None:
    monkeypatch.setattr(generate_script_module, "_script_service", script_service)
    monkeypatch.setattr("tasks.task_runner._run_service", SimpleNamespace(storage=storage))


def _invoke_task(**kwargs: Any) -> dict[str, object]:
    task = generate_script_module.generate_script
    run_callable = getattr(task, "run", task)
    return run_callable(**kwargs)


# ──────────────────────────────────────────────────────────────────────
# Happy-path tests
# ──────────────────────────────────────────────────────────────────────


def test_generate_script_happy_path_local_model_with_gpu_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(result="# Draft")
    entry = FakeEntry(requires_gpu=True, default_params={"temperature": 0.2})
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    lock_calls: list[str] = []
    release_calls: list[str] = []

    monkeypatch.setattr(
        "tasks.task_runner.acquire_gpu_lock",
        lambda client, task_id: (lock_calls.append(task_id) or f"{task_id}:fake-token"),
    )
    monkeypatch.setattr(
        "tasks.task_runner.release_gpu_lock",
        lambda client, token: release_calls.append(token.split(":")[0]) or True,
    )

    script_service = FakeScriptService()
    storage = _make_storage(run_id=101, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=101, idea_brief="A city mystery", model_key="qwen3-4b")

    assert result["status"] == "success"
    assert result["provider_type"] == "ollama"
    assert result["endpoint"] == "http://ollama:11434"
    assert result["gpu_lock_acquired_at"] is not None
    assert result["gpu_lock_released_at"] is not None
    assert lock_calls == ["run-101"]
    assert release_calls == ["run-101"]
    assert script_service.calls == [(101, "generated_by_model", "# Draft")]
    # get_run (stage guard) + update_run (advance to SCRIPT_REVIEW)
    assert storage.calls == [(101, {"current_stage": "SCRIPT_REVIEW", "status": "paused"})]
    assert provider.calls[0][1] == {"temperature": 0.2}


def test_generate_script_happy_path_external_model_without_gpu_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(result="Script from external")
    entry = FakeEntry(provider_type="openai", endpoint="https://api.openai.com", requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    monkeypatch.setattr(
        "tasks.task_runner.acquire_gpu_lock",
        lambda *_: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )
    monkeypatch.setattr(
        "tasks.task_runner.release_gpu_lock",
        lambda *_: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    script_service = FakeScriptService()
    storage = _make_storage(run_id=102, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=102, idea_brief="Ocean documentary", model_key="gpt-4.1")

    assert result["status"] == "success"
    assert result["provider_type"] == "openai"
    assert result["gpu_lock_acquired_at"] is None
    assert result["gpu_lock_released_at"] is None
    assert storage.calls == [(102, {"current_stage": "SCRIPT_REVIEW", "status": "paused"})]


def test_generate_script_appends_custom_instructions_to_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(result="Draft")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=108, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(
        run_id=108,
        idea_brief="Base idea",
        instructions="Use energetic narration",
    )

    assert result["status"] == "success"
    used_prompt = provider.calls[0][0]
    assert "Base idea" in used_prompt
    assert "Additional instructions:" in used_prompt
    assert "Use energetic narration" in used_prompt


# ──────────────────────────────────────────────────────────────────────
# Failure tests — task now re-raises, so pytest.raises is required
# ──────────────────────────────────────────────────────────────────────


def test_generate_script_provider_resolution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = FakeRegistry(
        entry=FakeEntry(),
        provider=FakeProvider(),
        resolve_error=KeyError("Model not found"),
    )
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=103, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(KeyError, match="Model not found"):
        _invoke_task(run_id=103, idea_brief="Unknown model", model_key="missing")

    assert script_service.calls == []
    assert storage.calls == [(103, {"current_stage": "FAILED", "status": "failed"})]


def test_generate_script_llm_generation_failure_sets_failed_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(error=RuntimeError("generation failed"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=104, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(
        generate_script_module.ProviderError, match="Provider failed script generation"
    ):
        _invoke_task(run_id=104, idea_brief="Failing generation")

    assert script_service.calls == []
    assert storage.calls == [(104, {"current_stage": "FAILED", "status": "failed"})]


def test_generate_script_gpu_lock_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=True)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    monkeypatch.setattr(
        "tasks.task_runner.acquire_gpu_lock",
        lambda *_: (_ for _ in ()).throw(TimeoutError("lock timeout")),
    )
    monkeypatch.setattr("tasks.task_runner.release_gpu_lock", lambda *_: None)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=105, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(TimeoutError, match="lock timeout"):
        _invoke_task(run_id=105, idea_brief="Lock timeout")

    assert script_service.calls == []
    assert storage.calls == [(105, {"current_stage": "FAILED", "status": "failed"})]


def test_generate_script_releases_gpu_lock_when_llm_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(error=RuntimeError("provider exploded"))
    entry = FakeEntry(requires_gpu=True)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    released: list[str] = []
    monkeypatch.setattr("tasks.task_runner.acquire_gpu_lock", lambda *_: "run-106:fake-token")
    monkeypatch.setattr(
        "tasks.task_runner.release_gpu_lock",
        lambda _, token: released.append(token.split(":")[0]) or True,
    )

    script_service = FakeScriptService()
    storage = _make_storage(run_id=106, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(
        generate_script_module.ProviderError, match="Provider failed script generation"
    ):
        _invoke_task(run_id=106, idea_brief="Failure with GPU")

    assert released == ["run-106"]
    assert storage.calls == [(106, {"current_stage": "FAILED", "status": "failed"})]


def test_generate_script_script_save_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(result="Draft text")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(error=RuntimeError("save failed"))
    storage = _make_storage(run_id=107, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(RuntimeError, match="save failed"):
        _invoke_task(run_id=107, idea_brief="Save failure")

    assert storage.calls == [(107, {"current_stage": "FAILED", "status": "failed"})]


# ──────────────────────────────────────────────────────────────────────
# Oracle-requested: stage guard
# ──────────────────────────────────────────────────────────────────────


def test_stage_guard_rejects_wrong_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task must refuse to run when the run is NOT in IDEA_READY or SCRIPT_GENERATING."""
    provider = FakeProvider(result="Should not be called")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=200, stage="SCRIPT_REVIEW")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(ValueError, match="expected one of"):
        _invoke_task(run_id=200, idea_brief="Should be blocked")

    # Provider should never have been called
    assert provider.calls == []
    assert script_service.calls == []
    # Run state must NOT be mutated — this is a validation rejection, not a failure
    assert storage.calls == []


def test_stage_guard_accepts_script_generating(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task should accept SCRIPT_GENERATING stage (retry / re-entry scenario)."""
    provider = FakeProvider(result="Retry draft")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=201, stage="SCRIPT_GENERATING")
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=201, idea_brief="Retry generation")

    assert result["status"] == "success"
    assert script_service.calls == [(201, "generated_by_model", "Retry draft")]


def test_stage_guard_run_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task must fail when run_id does not exist."""
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = FakeStorage()  # No runs at all
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(ValueError, match="Run 999 not found"):
        _invoke_task(run_id=999, idea_brief="Ghost run")

    assert provider.calls == []
    # Run state must NOT be mutated for a non-existent run
    assert storage.calls == []


# ──────────────────────────────────────────────────────────────────────
# Oracle-requested: re-raise propagation
# ──────────────────────────────────────────────────────────────────────


def test_failure_propagates_to_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task must re-raise exceptions so Celery marks the task as FAILURE."""
    provider = FakeProvider(error=RuntimeError("LLM exploded"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=300, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(
        generate_script_module.ProviderError, match="Provider failed script generation"
    ):
        _invoke_task(run_id=300, idea_brief="Propagation test")

    # The FAILED stage update must still have happened before re-raise
    assert storage.calls == [(300, {"current_stage": "FAILED", "status": "failed"})]


# ──────────────────────────────────────────────────────────────────────
# Oracle-requested: release_gpu_lock failure resilience
# ──────────────────────────────────────────────────────────────────────


def test_release_gpu_lock_failure_still_propagates_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If release_gpu_lock raises, the original generation error still propagates."""
    provider = FakeProvider(error=RuntimeError("generation boom"))
    entry = FakeEntry(requires_gpu=True)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    monkeypatch.setattr("tasks.task_runner.acquire_gpu_lock", lambda *_: "run-400:fake-token")
    monkeypatch.setattr(
        "tasks.task_runner.release_gpu_lock",
        lambda *_: (_ for _ in ()).throw(ConnectionError("redis gone")),
    )

    script_service = FakeScriptService()
    storage = _make_storage(run_id=400, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    # The original error should propagate (not the release_gpu_lock ConnectionError)
    with pytest.raises(
        generate_script_module.ProviderError, match="Provider failed script generation"
    ):
        _invoke_task(run_id=400, idea_brief="Lock release failure")


def test_update_run_failure_in_error_path_still_re_raises_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If update_run fails in the error handler, the original exception still propagates."""
    provider = FakeProvider(error=RuntimeError("original error"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=500, stage="IDEA_READY")
    storage.error = ConnectionError("DB down")  # update_run will fail too
    _patch_services(monkeypatch, script_service, storage)

    # Original error must still propagate even if FAILED-stage update fails
    with pytest.raises(
        generate_script_module.ProviderError, match="Provider failed script generation"
    ):
        _invoke_task(run_id=500, idea_brief="Double failure")


def test_stage_guard_wrong_stage_preserves_run_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """A run in SCRIPT_REVIEW must stay in SCRIPT_REVIEW after stage guard rejection."""
    provider = FakeProvider(result="Should not run")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=600, stage="SCRIPT_REVIEW")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(ValueError, match="expected one of"):
        _invoke_task(run_id=600, idea_brief="Stale duplicate task")

    # The run must NOT have been mutated at all
    assert storage.calls == []
    assert provider.calls == []
    # Verify the run still has its original stage
    run = storage._runs[600]
    assert run["current_stage"] == "SCRIPT_REVIEW"


def test_stage_guard_invalid_stage_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed current_stage value in storage should raise without marking FAILED."""
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    # Simulate corrupted stage value in storage
    storage = _make_storage(run_id=700, stage="BOGUS_STAGE")
    _patch_services(monkeypatch, script_service, storage)

    # RunStage("BOGUS_STAGE") will raise ValueError — should NOT mark run FAILED
    with pytest.raises(ValueError):
        _invoke_task(run_id=700, idea_brief="Corrupted stage")

    assert provider.calls == []
    assert storage.calls == []


def test_stage_guard_blocks_before_provider_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage guard must reject BEFORE provider resolution, so a bad model_key
    with a wrong-stage run does NOT mark the run as FAILED."""
    # Registry that will raise on resolve — simulates bad model_key
    registry = FakeRegistry(
        entry=FakeEntry(),
        provider=FakeProvider(),
        resolve_error=KeyError("Model not found"),
    )
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    # Run is already in SCRIPT_REVIEW — stale/duplicate task scenario
    storage = _make_storage(run_id=800, stage="SCRIPT_REVIEW")
    _patch_services(monkeypatch, script_service, storage)

    # Stage guard fires first, KeyError from resolve never reached
    with pytest.raises(ValueError, match="expected one of"):
        _invoke_task(run_id=800, idea_brief="Stale task with bad model")

    # Run state must NOT be mutated — stage guard rejected before provider setup
    assert storage.calls == []
    run = storage._runs[800]
    assert run["current_stage"] == "SCRIPT_REVIEW"


class RaceConditionStorage(FakeStorage):
    """Storage that simulates a competing task advancing the run between operations.

    After `advance_after` read/CAS operations on the target run_id, the run's
    stage is changed to `advanced_stage` before the operation reads it. This
    allows testing both:
    - Success path race: advance_after=1 (guard sees IDEA_READY, CAS sees advanced)
    - Failure path race: advance_after=1 (guard sees IDEA_READY, CAS sees advanced)
    """

    def __init__(
        self, run_id: int, initial_stage: str, advanced_stage: str, advance_after: int = 1
    ) -> None:
        super().__init__(runs={run_id: {"id": run_id, "current_stage": initial_stage}})
        self._target_id = run_id
        self._advanced_stage = advanced_stage
        self._advance_after = advance_after
        self._op_count = 0

    def _maybe_advance(self, run_id: int) -> None:
        """Simulate a competing task advancing the run after N operations."""
        if run_id == self._target_id:
            self._op_count += 1
            if self._op_count > self._advance_after:
                self._runs[run_id] = {"id": run_id, "current_stage": self._advanced_stage}

    async def get_run(self, run_id: int) -> dict[str, object] | None:
        self._maybe_advance(run_id)
        return self._runs.get(run_id)

    async def conditional_update_run(
        self,
        run_id: int,
        updates: dict[str, object],
        expected_stages: frozenset[str],
    rejected_statuses: frozenset[str] | None = None,
    ) -> tuple[bool, dict[str, object] | None]:
        """Atomic CAS — advance happens before the check, simulating a race."""
        self._maybe_advance(run_id)
        row = self._runs.get(run_id)
        if row is None:
            return False, None
        if row.get("current_stage") not in expected_stages:
            return False, dict(row)
        self.calls.append((run_id, updates))
        row.update(updates)
        self._runs[run_id] = row
        return True, dict(row)


def test_conditional_fail_skips_when_run_already_advanced(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a competing task advances the run to SCRIPT_REVIEW before the error handler
    runs, the error handler must NOT overwrite it to FAILED.

    Scenario: two duplicate tasks both pass the stage guard. Task A succeeds and
    advances the run to SCRIPT_REVIEW. Task B then fails during generation. Task B's
    error handler re-checks the stage and sees SCRIPT_REVIEW -> skips FAILED write.
    """
    provider = FakeProvider(error=RuntimeError("task B generation failed"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    # First get_run (stage guard) returns IDEA_READY -> task passes guard.
    # Second get_run (_conditional_fail) returns SCRIPT_REVIEW -> competing task advanced it.
    storage = RaceConditionStorage(
        run_id=900, initial_stage="IDEA_READY", advanced_stage="SCRIPT_REVIEW"
    )
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(
        generate_script_module.ProviderError, match="Provider failed script generation"
    ):
        _invoke_task(run_id=900, idea_brief="Duplicate task scenario")

    # Error handler must NOT have written FAILED -- run was already advanced
    assert storage.calls == []
    assert storage._runs[900]["current_stage"] == "SCRIPT_REVIEW"


def test_conditional_fail_marks_failed_when_still_in_generating_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the run is still in IDEA_READY at error time, the error handler should
    mark it as FAILED (normal failure path)."""
    provider = FakeProvider(error=RuntimeError("generation error"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = _make_storage(run_id=901, stage="IDEA_READY")
    _patch_services(monkeypatch, script_service, storage)

    with pytest.raises(
        generate_script_module.ProviderError, match="Provider failed script generation"
    ):
        _invoke_task(run_id=901, idea_brief="Normal failure")

    # Run was still in IDEA_READY -> FAILED write should happen
    assert storage.calls == [(901, {"current_stage": "FAILED", "status": "failed"})]


def test_success_transition_skips_when_run_already_advanced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a competing task advances the run past generation before this task's
    success transition, the SCRIPT_REVIEW write must be skipped.

    Scenario: two duplicate tasks both pass the stage guard (both see IDEA_READY).
    Task A completes and moves the run to VISUAL_PLAN_GENERATING. Task B then
    completes generation -- its success transition re-checks and sees the run is
    no longer in a generating stage, so it skips the SCRIPT_REVIEW write.
    """
    provider = FakeProvider(result="Duplicate draft")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    # First get_run (stage guard) returns IDEA_READY -> passes guard.
    # Second get_run (success transition check) returns VISUAL_PLAN_GENERATING
    # -> competing task already advanced the run further.
    storage = RaceConditionStorage(
        run_id=950, initial_stage="IDEA_READY", advanced_stage="VISUAL_PLAN_GENERATING"
    )
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=950, idea_brief="Duplicate success scenario")

    # Task still reports success (it generated and saved the draft)
    assert result["status"] == "success"
    # But the SCRIPT_REVIEW update_run must NOT have happened
    assert storage.calls == []
    # Draft was still saved (that is fine -- it will not be the active one)
    assert script_service.calls == [(950, "generated_by_model", "Duplicate draft")]
    # Run stays at the advanced stage, not overwritten to SCRIPT_REVIEW
    assert storage._runs[950]["current_stage"] == "VISUAL_PLAN_GENERATING"
