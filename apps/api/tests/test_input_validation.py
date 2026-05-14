# pyright: reportMissingImports=false
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from creator_service.ffmpeg_service import FFmpegService, RenderInput
from creator_service.json_script_parser import parse_json_scenes
from shorts_api.auth import CurrentUser
from shorts_api.routes.creator_runs_core import GenerateScriptRequest, generate_script_trigger
from shorts_api.routes.creator_runs_scene_assets import GenerateAudioRequest, generate_audio_trigger
from shorts_api.routes.creator_runs_utils import validate_model_key
from shorts_api.routes.creator_runs_utils import validate_path_id
from shorts_api.routes.creator_runs_visuals import ImageTuningParams


def test_image_tuning_params_rejects_invalid_sampler_name() -> None:
    with pytest.raises(ValueError, match="Invalid sampler"):
        ImageTuningParams(sampler_name="not-a-real-sampler")


def test_image_tuning_params_accepts_valid_sampler_name() -> None:
    params = ImageTuningParams(sampler_name="Euler")
    assert params.sampler_name == "Euler"


def test_validate_path_id_rejects_invalid_scene_id() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_path_id("bad$id", "scene_id")

    assert exc.value.status_code == 400
    assert "Invalid scene_id" in str(exc.value.detail)


def test_validate_path_id_rejects_too_long_scene_id() -> None:
    with pytest.raises(HTTPException) as exc:
        validate_path_id("a" * 129, "scene_id")

    assert exc.value.status_code == 400


def test_validate_path_id_accepts_valid_scene_id() -> None:
    value = validate_path_id("scene_123-abc", "scene_id")
    assert value == "scene_123-abc"


def test_json_script_parser_rejects_more_than_200_scenes() -> None:
    scenes = [{"text": f"scene {i}"} for i in range(201)]
    payload = {"scenes": scenes}

    with pytest.raises(ValueError, match="Too many scenes"):
        parse_json_scenes(json.dumps(payload))


def test_json_script_parser_rejects_text_longer_than_10000_chars() -> None:
    payload = {"scenes": [{"text": "x" * 10001}]}

    with pytest.raises(ValueError, match="text exceeds 10000 character limit"):
        parse_json_scenes(json.dumps(payload))


def test_ffmpeg_build_command_raises_on_mismatched_lengths() -> None:
    service = FFmpegService()
    data = RenderInput(
        image_paths=[Path("/tmp/a.png"), Path("/tmp/b.png")],
        audio_path=None,
        subtitle_path=None,
        scene_durations=[1.0],
    )

    with pytest.raises(ValueError, match="must have equal length"):
        service.build_command(data, Path("/tmp/out.mp4"))


def test_ffmpeg_build_command_raises_on_empty_image_paths() -> None:
    service = FFmpegService()
    data = RenderInput(
        image_paths=[],
        audio_path=None,
        subtitle_path=None,
        scene_durations=[],
    )

    with pytest.raises(ValueError, match="image_paths must not be empty"):
        service.build_command(data, Path("/tmp/out.mp4"))


def test_regenerate_scene_image_request_rejects_oversized_prompt() -> None:
    from pydantic import ValidationError
    from shorts_api.routes.creator_runs_scene_assets import RegenerateSceneImageRequest

    with pytest.raises(ValidationError):
        RegenerateSceneImageRequest(prompt_override="x" * 2001)


def test_regenerate_scene_image_request_accepts_valid_prompt() -> None:
    from shorts_api.routes.creator_runs_scene_assets import RegenerateSceneImageRequest

    req = RegenerateSceneImageRequest(prompt_override="a valid prompt")
    assert req.prompt_override == "a valid prompt"


def test_patch_scene_request_rejects_oversized_prompt() -> None:
    from pydantic import ValidationError
    from shorts_api.routes.creator_visual_plan import PatchSceneRequest

    with pytest.raises(ValidationError):
        PatchSceneRequest(prompt="x" * 2001)


def test_patch_scene_request_accepts_valid_prompt() -> None:
    from shorts_api.routes.creator_visual_plan import PatchSceneRequest

    req = PatchSceneRequest(prompt="a valid prompt")
    assert req.prompt == "a valid prompt"


def test_visual_scene_rejects_oversized_prompt() -> None:
    from pydantic import ValidationError
    from creator_domain.models.visual_plan import VisualScene

    with pytest.raises(ValidationError):
        VisualScene(
            scene_id="s1",
            section_id="s1",
            scene_index=0,
            section_type="narration",
            original_text="text",
            prompt="x" * 2001,
        )


def test_generate_script_request_rejects_oversized_instructions() -> None:
    from pydantic import ValidationError
    from shorts_api.routes.creator_runs_core import GenerateScriptRequest

    with pytest.raises(ValidationError):
        GenerateScriptRequest(instructions="x" * 32_001)


def test_generate_script_request_accepts_valid_instructions() -> None:
    from shorts_api.routes.creator_runs_core import GenerateScriptRequest

    req = GenerateScriptRequest(instructions="Write a short script about cats")
    assert req.instructions == "Write a short script about cats"


def test_generate_visual_plan_request_rejects_oversized_style_preset() -> None:
    from pydantic import ValidationError
    from shorts_api.routes.creator_runs_core import GenerateVisualPlanRequest

    with pytest.raises(ValidationError):
        GenerateVisualPlanRequest(style_preset="x" * 201)


def test_generate_visual_plan_request_accepts_valid_style_preset() -> None:
    from shorts_api.routes.creator_runs_core import GenerateVisualPlanRequest

    req = GenerateVisualPlanRequest(style_preset="cinematic")
    assert req.style_preset == "cinematic"


def test_import_markdown_request_rejects_oversized_style_preset() -> None:
    from pydantic import ValidationError
    from shorts_api.routes.creator_script import ImportMarkdownRequest

    with pytest.raises(ValidationError):
        ImportMarkdownRequest(markdown="# Hello", style_preset="x" * 201)


def test_import_json_request_rejects_oversized_style_preset() -> None:
    from pydantic import ValidationError
    from shorts_api.routes.creator_script import ImportJsonRequest

    with pytest.raises(ValidationError):
        ImportJsonRequest(json_script='{"scenes":[]}', style_preset="x" * 201)


def test_script_section_rejects_oversized_image_prompt() -> None:
    from pydantic import ValidationError
    from creator_domain.models.script_draft import ScriptSection

    with pytest.raises(ValidationError):
        ScriptSection(
            section_id="s1",
            type="narration",
            text="hello",
            image_prompt="x" * 2001,
        )


def test_script_section_accepts_valid_image_prompt() -> None:
    from creator_domain.models.script_draft import ScriptSection

    section = ScriptSection(
        section_id="s1",
        type="narration",
        text="hello",
        image_prompt="a beautiful sunset",
    )
    assert section.image_prompt == "a beautiful sunset"


def test_json_script_parser_rejects_oversized_image_prompt() -> None:
    payload = {"scenes": [{"text": "hello", "image_prompt": "x" * 2001}]}

    with pytest.raises(ValueError, match="image_prompt exceeds 2000 character limit"):
        parse_json_scenes(json.dumps(payload))


def _stub_registry_with_models() -> object:
    from creator_provider.registry import ModelCatalogEntry, ProviderCategory, ProviderRegistry

    registry = ProviderRegistry()
    registry.register_model(
        ModelCatalogEntry(
            model_key="some-tts-model",
            provider_type="stub",
            endpoint="http://stub",
            category=ProviderCategory.TTS,
        )
    )
    registry.register_model(
        ModelCatalogEntry(
            model_key="some-llm-model",
            provider_type="stub",
            endpoint="http://stub",
            category=ProviderCategory.LLM,
        )
    )
    registry.register_model(
        ModelCatalogEntry(
            model_key="sd15",
            provider_type="stub",
            endpoint="http://stub",
            category=ProviderCategory.IMAGE,
        )
    )
    registry.register_model(
        ModelCatalogEntry(
            model_key="qwen3-4b",
            provider_type="stub",
            endpoint="http://stub",
            category=ProviderCategory.LLM,
        )
    )
    registry.register_model(
        ModelCatalogEntry(
            model_key="qwen3-tts",
            provider_type="stub",
            endpoint="http://stub",
            category=ProviderCategory.TTS,
        )
    )
    return registry


def test_validate_model_key_rejects_wrong_expected_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from creator_provider.registry import ProviderRegistry

    registry = _stub_registry_with_models()
    monkeypatch.setattr(ProviderRegistry, "create_default", classmethod(lambda cls: registry))

    with pytest.raises(HTTPException) as exc:
        validate_model_key("some-tts-model", expected_category="llm")

    assert exc.value.status_code == 400
    assert "is a tts model" in str(exc.value.detail)
    assert "llm model is required" in str(exc.value.detail)


def test_validate_model_key_accepts_matching_expected_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from creator_provider.registry import ProviderRegistry

    registry = _stub_registry_with_models()
    monkeypatch.setattr(ProviderRegistry, "create_default", classmethod(lambda cls: registry))

    validate_model_key("some-llm-model", expected_category="llm")


@pytest.mark.asyncio
async def test_generate_script_rejects_image_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from creator_provider.registry import ProviderRegistry
    import shorts_api.routes.creator_runs_core as creator_runs_core

    registry = _stub_registry_with_models()
    monkeypatch.setattr(ProviderRegistry, "create_default", classmethod(lambda cls: registry))

    async def _no_active_tasks(_: int) -> bool:
        return False

    async def _fake_project(project_id: int, workspace_id: int | None = None) -> object:
        _ = workspace_id
        return SimpleNamespace(id=project_id, title="title", idea_brief="brief")

    async def _fake_dispatch(**_: object) -> dict[str, object]:
        return {"task_id": "t1"}

    monkeypatch.setattr(creator_runs_core, "_has_active_tasks_for_run", _no_active_tasks)
    monkeypatch.setattr(creator_runs_core.project_service, "get_project", _fake_project)
    monkeypatch.setattr(creator_runs_core, "cas_dispatch_with_rollback", _fake_dispatch)

    user = CurrentUser(user_id=1, workspace_id=1)
    run = SimpleNamespace(id=1, project_id=7, current_stage="IDEA_READY", restart_from=None)
    request = GenerateScriptRequest(model_key="sd15")

    with pytest.raises(HTTPException) as exc:
        await generate_script_trigger(run_id=1, request=request, access=(user, run))  # pyright: ignore[reportArgumentType]

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_generate_audio_rejects_llm_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from creator_provider.registry import ProviderRegistry
    import shorts_api.routes.creator_runs_scene_assets as creator_runs_scene_assets

    registry = _stub_registry_with_models()
    monkeypatch.setattr(ProviderRegistry, "create_default", classmethod(lambda cls: registry))

    async def _no_active_tasks(_: int) -> bool:
        return False

    async def _fake_dispatch(**_: object) -> dict[str, object]:
        return {"task_id": "t1"}

    monkeypatch.setattr(creator_runs_scene_assets, "_has_active_tasks_for_run", _no_active_tasks)
    monkeypatch.setattr(creator_runs_scene_assets, "cas_dispatch_with_rollback", _fake_dispatch)

    user = CurrentUser(user_id=1, workspace_id=1)
    run = SimpleNamespace(
        id=1, project_id=7, current_stage="VISUAL_ASSET_REVIEW", restart_from=None
    )
    request = GenerateAudioRequest(tts_model="qwen3-4b")

    with pytest.raises(HTTPException) as exc:
        await generate_audio_trigger(run_id=1, request=request, access=(user, run))  # pyright: ignore[reportArgumentType]

    assert exc.value.status_code == 400
