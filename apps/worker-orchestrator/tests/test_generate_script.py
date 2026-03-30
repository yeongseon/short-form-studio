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
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, dict[str, object]]] = []

    async def update_run(self, run_id: int, updates: dict[str, object]) -> dict[str, object]:
        self.calls.append((run_id, updates))
        if self.error is not None:
            raise self.error
        return {"id": run_id, **updates}


class FakeScriptService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[int, str, str | None]] = []

    async def save_draft(self, run_id: int, source_type: str, markdown_content: str | None) -> dict[str, object]:
        self.calls.append((run_id, source_type, markdown_content))
        if self.error is not None:
            raise self.error
        return {"run_id": run_id, "source_type": source_type, "markdown_content": markdown_content}


class FakeRegistry:
    def __init__(self, entry: FakeEntry, provider: FakeProvider, resolve_error: Exception | None = None) -> None:
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

    monkeypatch.setattr(generate_script_module, "ProviderRegistry", _ProviderRegistry)


def _patch_redis(monkeypatch: pytest.MonkeyPatch, redis_client: object) -> None:
    redis_stub = SimpleNamespace(Redis=SimpleNamespace(from_url=lambda _: redis_client))
    monkeypatch.setattr(generate_script_module, "redis", redis_stub)


def _patch_services(
    monkeypatch: pytest.MonkeyPatch,
    script_service: FakeScriptService,
    storage: FakeStorage,
) -> None:
    monkeypatch.setattr(generate_script_module, "_script_service", script_service)
    monkeypatch.setattr(generate_script_module, "_run_service", SimpleNamespace(storage=storage))


def _invoke_task(**kwargs: Any) -> dict[str, object]:
    task = generate_script_module.generate_script
    run_callable = getattr(task, "run", task)
    return run_callable(**kwargs)


def test_generate_script_happy_path_local_model_with_gpu_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(result="# Draft")
    entry = FakeEntry(requires_gpu=True, default_params={"temperature": 0.2})
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    redis_client = object()
    _patch_redis(monkeypatch, redis_client)

    lock_calls: list[str] = []
    release_calls: list[str] = []

    monkeypatch.setattr(generate_script_module, "acquire_gpu_lock", lambda client, task_id: lock_calls.append(task_id))
    monkeypatch.setattr(generate_script_module, "release_gpu_lock", lambda client, task_id: release_calls.append(task_id))

    script_service = FakeScriptService()
    storage = FakeStorage()
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
    assert storage.calls == [(101, {"current_stage": "SCRIPT_REVIEW", "status": "running"})]
    assert provider.calls[0][1] == {"temperature": 0.2}


def test_generate_script_happy_path_external_model_without_gpu_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(result="Script from external")
    entry = FakeEntry(provider_type="openai", endpoint="https://api.openai.com", requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    monkeypatch.setattr(generate_script_module, "acquire_gpu_lock", lambda *_: (_ for _ in ()).throw(RuntimeError("unexpected")))
    monkeypatch.setattr(generate_script_module, "release_gpu_lock", lambda *_: (_ for _ in ()).throw(RuntimeError("unexpected")))

    script_service = FakeScriptService()
    storage = FakeStorage()
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=102, idea_brief="Ocean documentary", model_key="gpt-4.1")

    assert result["status"] == "success"
    assert result["provider_type"] == "openai"
    assert result["gpu_lock_acquired_at"] is None
    assert result["gpu_lock_released_at"] is None
    assert storage.calls == [(102, {"current_stage": "SCRIPT_REVIEW", "status": "running"})]


def test_generate_script_provider_resolution_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = FakeRegistry(
        entry=FakeEntry(),
        provider=FakeProvider(),
        resolve_error=KeyError("Model not found"),
    )
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = FakeStorage()
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=103, idea_brief="Unknown model", model_key="missing")

    assert result["status"] == "failed"
    assert "Model not found" in str(result["error"])
    assert script_service.calls == []
    assert storage.calls == [(103, {"current_stage": "FAILED", "status": "failed"})]


def test_generate_script_llm_generation_failure_sets_failed_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(error=RuntimeError("generation failed"))
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = FakeStorage()
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=104, idea_brief="Failing generation")

    assert result["status"] == "failed"
    assert result["error"] == "generation failed"
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
        generate_script_module,
        "acquire_gpu_lock",
        lambda *_: (_ for _ in ()).throw(TimeoutError("lock timeout")),
    )
    monkeypatch.setattr(generate_script_module, "release_gpu_lock", lambda *_: None)

    script_service = FakeScriptService()
    storage = FakeStorage()
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=105, idea_brief="Lock timeout")

    assert result["status"] == "failed"
    assert result["error"] == "lock timeout"
    assert result["gpu_lock_acquired_at"] is None
    assert result["gpu_lock_released_at"] is None
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
    monkeypatch.setattr(generate_script_module, "acquire_gpu_lock", lambda *_: True)
    monkeypatch.setattr(generate_script_module, "release_gpu_lock", lambda _, task_id: released.append(task_id))

    script_service = FakeScriptService()
    storage = FakeStorage()
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=106, idea_brief="Failure with GPU")

    assert result["status"] == "failed"
    assert released == ["run-106"]
    assert result["gpu_lock_released_at"] is not None
    assert storage.calls == [(106, {"current_stage": "FAILED", "status": "failed"})]


def test_generate_script_script_save_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(result="Draft text")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService(error=RuntimeError("save failed"))
    storage = FakeStorage()
    _patch_services(monkeypatch, script_service, storage)

    result = _invoke_task(run_id=107, idea_brief="Save failure")

    assert result["status"] == "failed"
    assert result["error"] == "save failed"
    assert storage.calls == [(107, {"current_stage": "FAILED", "status": "failed"})]


def test_generate_script_appends_custom_instructions_to_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeProvider(result="Draft")
    entry = FakeEntry(requires_gpu=False)
    registry = FakeRegistry(entry=entry, provider=provider)
    _patch_registry(monkeypatch, registry)

    script_service = FakeScriptService()
    storage = FakeStorage()
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
