from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from tasks import generate_visual_plan as generate_visual_plan_module


@dataclass
class FakeEntry:
    provider_type: str = "ollama"
    endpoint: str = "http://ollama:11434"
    requires_gpu: bool = True
    default_params: dict[str, object] | None = None


class FakeProvider:
    def __init__(self, result: str = "[]", error: Exception | None = None) -> None:
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


def _make_storage(
    run_id: int = 101, stage: str = "VISUAL_PLAN_GENERATING", **extra: Any
) -> FakeStorage:
    """Create a FakeStorage pre-populated with a single run in the given stage."""
    run_row: dict[str, object] = {"id": run_id, "current_stage": stage, **extra}
    return FakeStorage(runs={run_id: run_row})


@dataclass
class FakeScriptDraft:
    """Minimal fake for the ScriptDraft domain model returned by script_service."""

    markdown_content: str | None = None
    structured_script: list[Any] | None = None


class FakeScriptService:
    def __init__(
        self,
        draft: FakeScriptDraft | None = None,
        error: Exception | None = None,
    ) -> None:
        self.draft = draft
        self.error = error

    async def get_active_draft(self, run_id: int) -> FakeScriptDraft | None:
        if self.error is not None:
            raise self.error
        return self.draft


@dataclass
class FakeSection:
    """Minimal structured script section with model_dump support."""

    section_id: str = "sec-0"
    type: str = "hook"
    text: str = "Hook text"

    def model_dump(self, mode: str = "python") -> dict[str, str]:
        return {"section_id": self.section_id, "type": self.type, "text": self.text}


class FakeVisualPlanService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, int]] = []  # (run_id, num_scenes)

    async def save_plan(
        self,
        run_id: int,
        scenes: list[Any],
        *,
        idempotency_key: str | None = None,
    ) -> SimpleNamespace:
        self.calls.append((run_id, len(scenes)))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(run_id=run_id, scenes=scenes, version=1)


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
    class _ProviderRegistry:
        @staticmethod
        def create_default() -> FakeRegistry:
            return registry

    monkeypatch.setattr(generate_visual_plan_module, "ProviderRegistry", _ProviderRegistry)


def _patch_redis(monkeypatch: pytest.MonkeyPatch, redis_client: object) -> None:
    redis_stub = SimpleNamespace(Redis=SimpleNamespace(from_url=lambda _: redis_client))
    monkeypatch.setattr("tasks.task_runner.redis", redis_stub)


def _patch_services(
    monkeypatch: pytest.MonkeyPatch,
    script_service: FakeScriptService,
    visual_plan_service: FakeVisualPlanService,
    storage: FakeStorage,
) -> None:
    monkeypatch.setattr(generate_visual_plan_module, "_script_service", script_service)
    monkeypatch.setattr(generate_visual_plan_module, "_visual_plan_service", visual_plan_service)
    monkeypatch.setattr("tasks.task_runner._run_service", SimpleNamespace(storage=storage))


def _invoke_task(**kwargs: Any) -> dict[str, object]:
    task = generate_visual_plan_module.generate_visual_plan
    run_callable = getattr(task, "run", task)
    return run_callable(**kwargs)


def _make_llm_response(sections: list[dict[str, str]]) -> str:
    """Build a valid LLM JSON response matching the expected format."""
    scenes = []
    for sec in sections:
        scenes.append(
            {
                "section_id": sec.get("section_id", "sec-0"),
                "prompt": f"Visual for {sec.get('text', '')}",
                "style_tags": ["cinematic"],
                "mood": "dramatic",
                "composition": "wide shot",
            }
        )
    return json.dumps(scenes)


# ──────────────────────────────────────────────────────────────────────
# Happy-path tests
# ──────────────────────────────────────────────────────────────────────


def test_happy_path_local_model_with_gpu_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [FakeSection(section_id="sec-1", type="hook", text="Opening hook")]
    llm_response = _make_llm_response([s.model_dump() for s in sections])
    provider = FakeProvider(result=llm_response)
    entry = FakeEntry(requires_gpu=True, default_params={"temperature": 0.3})
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

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=101, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    result = _invoke_task(run_id=101, model_key="qwen3-4b")

    assert result["status"] == "success"
    assert result["provider_type"] == "ollama"
    assert result["endpoint"] == "http://ollama:11434"
    assert result["gpu_lock_acquired_at"] is not None
    assert result["gpu_lock_released_at"] is not None
    assert result["scene_count"] == 1
    assert lock_calls == ["run-101"]
    assert release_calls == ["run-101"]
    assert visual_plan_service.calls == [(101, 1)]
    assert storage.calls == [(101, {"current_stage": "VISUAL_PLAN_REVIEW", "status": "running"})]
    assert provider.calls[0][1] == {"temperature": 0.3}


def test_happy_path_external_model_without_gpu_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [FakeSection(section_id="sec-1", type="hook", text="Hook")]
    llm_response = _make_llm_response([s.model_dump() for s in sections])
    provider = FakeProvider(result=llm_response)
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

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=102, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    result = _invoke_task(run_id=102, model_key="gpt-4.1")

    assert result["status"] == "success"
    assert result["provider_type"] == "openai"
    assert result["gpu_lock_acquired_at"] is None
    assert result["gpu_lock_released_at"] is None
    assert storage.calls == [(102, {"current_stage": "VISUAL_PLAN_REVIEW", "status": "running"})]


def test_happy_path_multi_section_script(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [
        FakeSection(section_id="sec-1", type="hook", text="Opening"),
        FakeSection(section_id="sec-2", type="body", text="Main content"),
        FakeSection(section_id="sec-3", type="cta", text="Call to action"),
    ]
    llm_response = _make_llm_response([s.model_dump() for s in sections])
    provider = FakeProvider(result=llm_response)
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=103, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    result = _invoke_task(run_id=103)

    assert result["status"] == "success"
    assert result["scene_count"] == 3
    assert visual_plan_service.calls == [(103, 3)]


def test_happy_path_markdown_fallback_single_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """When draft has only markdown_content (no structured_script), produces a single scene."""
    llm_response = json.dumps(
        [
            {
                "section_id": "sec-0",
                "prompt": "Visual for markdown",
                "style_tags": ["minimalist"],
                "mood": "calm",
                "composition": "medium shot",
            }
        ]
    )
    provider = FakeProvider(result=llm_response)
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(
        draft=FakeScriptDraft(markdown_content="# My Script\nSome content")
    )
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=104, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    result = _invoke_task(run_id=104)

    assert result["status"] == "success"
    assert result["scene_count"] == 1
    assert visual_plan_service.calls == [(104, 1)]


def test_style_preset_passed_to_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [FakeSection()]
    llm_response = _make_llm_response([s.model_dump() for s in sections])
    provider = FakeProvider(result=llm_response)
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=105, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    result = _invoke_task(run_id=105, style_preset="anime")

    assert result["status"] == "success"
    used_prompt = provider.calls[0][0]
    assert "anime" in used_prompt


# ──────────────────────────────────────────────────────────────────────
# Failure tests — task re-raises, pytest.raises required
# ──────────────────────────────────────────────────────────────────────


def test_provider_resolution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = FakeRegistry(
        entry=FakeEntry(),
        provider=FakeProvider(),
        resolve_error=KeyError("Model not found"),
    )
    _patch_registry(monkeypatch, registry)

    sections = [FakeSection()]
    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=201, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(KeyError, match="Model not found"):
        _invoke_task(run_id=201, model_key="missing")

    assert visual_plan_service.calls == []
    assert storage.calls == [(201, {"current_stage": "FAILED", "status": "failed"})]


def test_llm_generation_failure_sets_failed_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(error=RuntimeError("generation failed"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    sections = [FakeSection()]
    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=202, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(
        generate_visual_plan_module.ProviderError,
        match="Provider failed visual plan generation",
    ):
        _invoke_task(run_id=202)

    assert visual_plan_service.calls == []
    assert storage.calls == [(202, {"current_stage": "FAILED", "status": "failed"})]


def test_gpu_lock_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
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

    sections = [FakeSection()]
    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=203, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(TimeoutError, match="lock timeout"):
        _invoke_task(run_id=203)

    assert visual_plan_service.calls == []
    assert storage.calls == [(203, {"current_stage": "FAILED", "status": "failed"})]


def test_releases_gpu_lock_when_llm_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(error=RuntimeError("provider exploded"))
    entry = FakeEntry(requires_gpu=True)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    released: list[str] = []
    monkeypatch.setattr(
        "tasks.task_runner.acquire_gpu_lock", lambda _, task_id: f"{task_id}:fake-token"
    )
    monkeypatch.setattr(
        "tasks.task_runner.release_gpu_lock",
        lambda _, token: released.append(token.split(":")[0]) or True,
    )

    sections = [FakeSection()]
    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=204, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(
        generate_visual_plan_module.ProviderError,
        match="Provider failed visual plan generation",
    ):
        _invoke_task(run_id=204)

    assert released == ["run-204"]
    assert storage.calls == [(204, {"current_stage": "FAILED", "status": "failed"})]


def test_visual_plan_save_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    sections = [FakeSection()]
    llm_response = _make_llm_response([s.model_dump() for s in sections])
    provider = FakeProvider(result=llm_response)
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService(error=RuntimeError("save failed"))
    storage = _make_storage(run_id=205, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(RuntimeError, match="save failed"):
        _invoke_task(run_id=205)

    assert storage.calls == [(205, {"current_stage": "FAILED", "status": "failed"})]


# ──────────────────────────────────────────────────────────────────────
# Stage guard tests
# ──────────────────────────────────────────────────────────────────────


def test_stage_guard_rejects_wrong_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task must refuse to run when the run is NOT in VISUAL_PLAN_SETUP or VISUAL_PLAN_GENERATING."""
    provider = FakeProvider(result="Should not be called")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=[FakeSection()]))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=301, stage="VISUAL_PLAN_REVIEW")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(ValueError, match="expected one of"):
        _invoke_task(run_id=301)

    assert provider.calls == []
    assert visual_plan_service.calls == []
    assert storage.calls == []


def test_stage_guard_accepts_visual_plan_generating(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task should accept VISUAL_PLAN_GENERATING stage (retry / re-entry scenario)."""
    sections = [FakeSection()]
    llm_response = _make_llm_response([s.model_dump() for s in sections])
    provider = FakeProvider(result=llm_response)
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=302, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    result = _invoke_task(run_id=302)

    assert result["status"] == "success"
    assert visual_plan_service.calls == [(302, 1)]


def test_stage_guard_run_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task must fail when run_id does not exist."""
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    visual_plan_service = FakeVisualPlanService()
    storage = FakeStorage()  # No runs at all
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(ValueError, match="Run 999 not found"):
        _invoke_task(run_id=999)

    assert provider.calls == []
    assert storage.calls == []


def test_stage_guard_no_script_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task must fail when no script draft exists for the run."""
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=None)
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=303, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(ValueError, match="No script draft found"):
        _invoke_task(run_id=303)

    assert provider.calls == []
    assert storage.calls == []


def test_stage_guard_empty_script_content(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task must fail when script draft has no content (no sections, no markdown)."""
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft())  # no structured_script, no markdown
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=304, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(ValueError, match="has no content"):
        _invoke_task(run_id=304)

    assert provider.calls == []
    assert storage.calls == []


def test_stage_guard_invalid_stage_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed current_stage in storage should raise without marking FAILED."""
    provider = FakeProvider()
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=305, stage="BOGUS_STAGE")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(ValueError):
        _invoke_task(run_id=305)

    assert provider.calls == []
    assert storage.calls == []


def test_stage_guard_blocks_before_provider_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stage guard must reject BEFORE provider resolution, so a bad model_key
    with a wrong-stage run does NOT mark the run as FAILED."""
    registry = FakeRegistry(
        entry=FakeEntry(),
        provider=FakeProvider(),
        resolve_error=KeyError("Model not found"),
    )
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=[FakeSection()]))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=306, stage="VISUAL_PLAN_REVIEW")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(ValueError, match="expected one of"):
        _invoke_task(run_id=306, model_key="bad-model")

    assert storage.calls == []
    run = storage._runs[306]
    assert run["current_stage"] == "VISUAL_PLAN_REVIEW"


# ──────────────────────────────────────────────────────────────────────
# Re-raise propagation and lock resilience
# ──────────────────────────────────────────────────────────────────────


def test_failure_propagates_to_celery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task must re-raise exceptions so Celery marks the task as FAILURE."""
    sections = [FakeSection()]
    provider = FakeProvider(error=RuntimeError("LLM exploded"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=401, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(
        generate_visual_plan_module.ProviderError,
        match="Provider failed visual plan generation",
    ):
        _invoke_task(run_id=401)

    assert storage.calls == [(401, {"current_stage": "FAILED", "status": "failed"})]


def test_release_gpu_lock_failure_still_propagates_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If release_gpu_lock raises, the original generation error still propagates."""
    sections = [FakeSection()]
    provider = FakeProvider(error=RuntimeError("generation boom"))
    entry = FakeEntry(requires_gpu=True)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    monkeypatch.setattr(
        "tasks.task_runner.acquire_gpu_lock", lambda _, task_id: f"{task_id}:fake-token"
    )
    monkeypatch.setattr(
        "tasks.task_runner.release_gpu_lock",
        lambda *_: (_ for _ in ()).throw(ConnectionError("redis gone")),
    )

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=402, stage="VISUAL_PLAN_GENERATING")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(
        generate_visual_plan_module.ProviderError,
        match="Provider failed visual plan generation",
    ):
        _invoke_task(run_id=402)


def test_update_run_failure_in_error_path_still_re_raises_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If conditional_update_run fails in error handler, original exception still propagates."""
    sections = [FakeSection()]
    provider = FakeProvider(error=RuntimeError("original error"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = _make_storage(run_id=403, stage="VISUAL_PLAN_GENERATING")
    storage.error = ConnectionError("DB down")
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(
        generate_visual_plan_module.ProviderError,
        match="Provider failed visual plan generation",
    ):
        _invoke_task(run_id=403)


# ──────────────────────────────────────────────────────────────────────
# Race condition / CAS tests
# ──────────────────────────────────────────────────────────────────────


class RaceConditionStorage(FakeStorage):
    """Storage that simulates a competing task advancing the run between operations."""

    def __init__(
        self, run_id: int, initial_stage: str, advanced_stage: str, advance_after: int = 1
    ) -> None:
        super().__init__(runs={run_id: {"id": run_id, "current_stage": initial_stage}})
        self._target_id = run_id
        self._advanced_stage = advanced_stage
        self._advance_after = advance_after
        self._op_count = 0

    def _maybe_advance(self, run_id: int) -> None:
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
    """If a competing task advances the run before this task's error handler,
    the FAILED write must be skipped."""
    sections = [FakeSection()]
    provider = FakeProvider(error=RuntimeError("task B failed"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = RaceConditionStorage(
        run_id=501, initial_stage="VISUAL_PLAN_SETUP", advanced_stage="VISUAL_PLAN_REVIEW"
    )
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    with pytest.raises(
        generate_visual_plan_module.ProviderError,
        match="Provider failed visual plan generation",
    ):
        _invoke_task(run_id=501)

    assert storage.calls == []
    assert storage._runs[501]["current_stage"] == "VISUAL_PLAN_REVIEW"


def test_success_transition_skips_when_run_already_advanced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a competing task advances the run past visual plan generation,
    the VISUAL_PLAN_REVIEW write must be skipped."""
    sections = [FakeSection()]
    llm_response = _make_llm_response([s.model_dump() for s in sections])
    provider = FakeProvider(result=llm_response)
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(draft=FakeScriptDraft(structured_script=sections))
    visual_plan_service = FakeVisualPlanService()
    storage = RaceConditionStorage(
        run_id=502, initial_stage="VISUAL_PLAN_SETUP", advanced_stage="VISUAL_ASSET_GENERATING"
    )
    _patch_services(monkeypatch, script_service, visual_plan_service, storage)

    result = _invoke_task(run_id=502)

    assert result["status"] == "success"
    assert storage.calls == []
    assert visual_plan_service.calls == [(502, 1)]
    assert storage._runs[502]["current_stage"] == "VISUAL_ASSET_GENERATING"


# ──────────────────────────────────────────────────────────────────────
# LLM response parsing tests
# ──────────────────────────────────────────────────────────────────────


def test_parse_llm_response_handles_markdown_fenced_json() -> None:
    """LLM response wrapped in ```json fencing should still parse."""
    sections = [{"section_id": "sec-1", "type": "hook", "text": "Hook"}]
    fenced = '```json\n[{"section_id": "sec-1", "prompt": "test", "style_tags": [], "mood": "calm", "composition": "wide"}]\n```'

    result = generate_visual_plan_module._parse_llm_response(fenced, sections)

    assert len(result) == 1
    assert result[0].prompt == "test"
    assert result[0].mood == "calm"


def test_parse_llm_response_invalid_json_produces_default_scenes() -> None:
    """Invalid JSON should produce fallback scenes with default prompts."""
    sections = [
        {"section_id": "sec-1", "type": "hook", "text": "Hook text here"},
        {"section_id": "sec-2", "type": "body", "text": "Body text here"},
    ]
    result = generate_visual_plan_module._parse_llm_response("this is not json", sections)

    assert len(result) == 2
    assert result[0].scene_id == "scene-sec-1"
    assert "Hook text here" in result[0].prompt
    assert result[1].scene_id == "scene-sec-2"


def test_parse_llm_response_missing_section_gets_default() -> None:
    """Sections not matched by LLM output get a default scene."""
    sections = [
        {"section_id": "sec-1", "type": "hook", "text": "Hook"},
        {"section_id": "sec-2", "type": "body", "text": "Body"},
    ]
    llm_json = json.dumps(
        [
            {
                "section_id": "sec-1",
                "prompt": "LLM prompt for hook",
                "style_tags": ["anime"],
                "mood": "energetic",
                "composition": "close-up",
            }
        ]
    )

    result = generate_visual_plan_module._parse_llm_response(llm_json, sections)

    assert len(result) == 2
    assert result[0].prompt == "LLM prompt for hook"
    assert result[0].style_tags == ["anime"]
    assert "Body" in result[1].prompt  # Default prompt with section text
    assert result[1].style_tags == []  # Default empty
