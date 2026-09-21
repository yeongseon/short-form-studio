"""SF-67: reusable voice presets for short drafts (provider/voice/settings).

A VoicePreset is a reusable, CREDENTIAL-FREE selection of a TTS model_key + voice_id
+ provider-agnostic settings, independent of recipes. It carries NO api key, secret,
or endpoint — credentials stay in the environment (resolve_api_key) and are never
embedded in a preset, a resolved selection, or an error. resolve_voice_selection
derives the provider from ProviderRegistry.resolve(model_key) (requiring a TTS
model), and reports availability by checking configured-ness of a remote provider's
key as a boolean only — the key VALUE is never read into a result or message.
Unsupported (unknown/non-TTS model) and missing-provider (remote key not configured)
produce distinct typed errors.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_provider.registry import ModelCatalogEntry, ProviderCategory, ProviderRegistry
from creator_service.voice_preset import (
    VOICE_PRESETS,
    ResolvedVoiceSelection,
    VoicePreset,
    resolve_voice_preset,
    resolve_voice_selection,
    voice_preset_ids,
)


def _registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register_model(
        ModelCatalogEntry(
            model_key="qwen3-tts", provider_type="qwen_tts", endpoint="http://tts",
            category=ProviderCategory.TTS, requires_gpu=True, is_local=True,
        )
    )
    registry.register_model(
        ModelCatalogEntry(
            model_key="elevenlabs-multilingual-v2", provider_type="elevenlabs_tts",
            endpoint="https://api.elevenlabs.io", category=ProviderCategory.TTS,
            requires_gpu=False, is_local=False,
        )
    )
    registry.register_model(
        ModelCatalogEntry(
            model_key="openai-tts-1", provider_type="openai_tts", endpoint="https://api.openai.com",
            category=ProviderCategory.TTS, requires_gpu=False, is_local=False,
            default_params={"voice": "alloy"},
        )
    )
    registry.register_model(
        ModelCatalogEntry(
            model_key="whisper-small", provider_type="whisper", endpoint="http://stt",
            category=ProviderCategory.STT, requires_gpu=True, is_local=True,
        )
    )
    return registry


def _all_configured(provider_name: str) -> bool:
    return True


def _none_configured(provider_name: str) -> bool:
    return False


# ------------------------- preset registry + id resolution -------------------------


def test_ships_credential_free_voice_presets() -> None:
    assert VOICE_PRESETS
    for preset in VOICE_PRESETS.values():
        assert isinstance(preset, VoicePreset)
        assert preset.model_key
        assert preset.voice_id


def test_preset_ids_are_a_sorted_immutable_tuple() -> None:
    ids = voice_preset_ids()
    assert isinstance(ids, tuple)
    assert list(ids) == sorted(VOICE_PRESETS)


def test_resolve_returns_the_registered_preset() -> None:
    any_id = voice_preset_ids()[0]
    assert resolve_voice_preset(any_id) == VOICE_PRESETS[any_id]


def test_resolve_rejects_unknown_preset_id() -> None:
    with pytest.raises(ValidationError, match="preset"):
        resolve_voice_preset("no_such_voice")


@pytest.mark.parametrize("bad", [None, 123, True, ""])
def test_resolve_rejects_non_string_or_blank_preset_id(bad: object) -> None:
    with pytest.raises(ValidationError, match="preset"):
        resolve_voice_preset(bad)  # type: ignore[arg-type]


# ------------------------- preset construction validation -------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"id": "", "model_key": "m", "voice_id": "v"},
        {"id": "p", "model_key": "", "voice_id": "v"},
        {"id": "p", "model_key": "m", "voice_id": ""},
    ],
)
def test_rejects_blank_required_fields(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VoicePreset(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "settings",
    [
        {"speed": None},
        {"speed": float("nan")},
        {"speed": float("inf")},
        {"nested": {"a": 1}},
        {"list": [1, 2]},
        {"": "blankkey"},
    ],
)
def test_rejects_invalid_settings(settings: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        VoicePreset(id="p", model_key="m", voice_id="v", settings=settings)


def test_accepts_primitive_settings() -> None:
    preset = VoicePreset(
        id="p", model_key="m", voice_id="v",
        settings={"speed": 1.0, "stability": 0.5, "style": "warm", "boost": True, "n": 3},
    )
    assert preset.settings["speed"] == 1.0


# ------------------------- registry/model resolution -------------------------


def test_resolves_a_local_tts_preset_without_touching_the_key_checker() -> None:
    preset = VoicePreset(id="p", model_key="qwen3-tts", voice_id="ko-warm")

    def _explode(provider_name: str) -> bool:
        raise AssertionError("local TTS must not check credentials")

    selection = resolve_voice_selection(
        preset, registry=_registry(), key_configured=_explode
    )
    assert isinstance(selection, ResolvedVoiceSelection)
    assert selection.model_key == "qwen3-tts"
    assert selection.provider_type == "qwen_tts"
    assert selection.voice_id == "ko-warm"


def test_resolves_a_remote_tts_preset_when_key_configured() -> None:
    preset = VoicePreset(id="p", model_key="openai-tts-1", voice_id="alloy")
    selection = resolve_voice_selection(
        preset, registry=_registry(), key_configured=_all_configured
    )
    assert selection.provider_type == "openai_tts"


def test_unknown_model_is_an_unsupported_error() -> None:
    preset = VoicePreset(id="p", model_key="ghost-tts", voice_id="v")
    with pytest.raises(ValidationError, match="not supported|unknown model|unsupported") as exc:
        resolve_voice_selection(preset, registry=_registry(), key_configured=_all_configured)
    assert exc.value.__cause__ is not None


def test_non_tts_model_is_an_unsupported_error() -> None:
    preset = VoicePreset(id="p", model_key="whisper-small", voice_id="v")
    with pytest.raises(ValidationError, match="not a voice|TTS|not supported"):
        resolve_voice_selection(preset, registry=_registry(), key_configured=_all_configured)


def test_remote_tts_with_missing_key_is_a_distinct_missing_provider_error() -> None:
    preset = VoicePreset(id="p", model_key="elevenlabs-multilingual-v2", voice_id="rachel")
    with pytest.raises(ValidationError, match="not configured|missing") as exc:
        resolve_voice_selection(preset, registry=_registry(), key_configured=_none_configured)
    # distinct from the unsupported error: this one names the env var guidance
    assert "ELEVENLABS_API_KEY" in str(exc.value)


def test_remote_provider_without_a_credential_mapping_is_unsupported() -> None:
    # A remote TTS model whose provider_type has no key mapping cannot be resolved
    # safely, so it is rejected rather than silently treated as keyless.
    registry = ProviderRegistry()
    registry.register_model(
        ModelCatalogEntry(
            model_key="mystery-tts", provider_type="mystery_tts", endpoint="https://x",
            category=ProviderCategory.TTS, requires_gpu=False, is_local=False,
        )
    )
    preset = VoicePreset(id="p", model_key="mystery-tts", voice_id="v")
    with pytest.raises(ValidationError, match="credential resolver|no credential|not supported"):
        resolve_voice_selection(preset, registry=registry, key_configured=_all_configured)


# ------------------------- credential safety -------------------------


def test_preset_has_no_credential_fields() -> None:
    preset = VOICE_PRESETS[voice_preset_ids()[0]]
    for field in ("api_key", "key", "secret", "token", "credential"):
        assert not hasattr(preset, field)


def test_no_key_value_leaks_into_selection_or_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    # Even with a real-looking secret in the env, no resolved selection, repr, or
    # error text may contain the key VALUE — only configured-ness is used.
    secret = "sk-test-SECRET-value-1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")

    preset = VoicePreset(id="p", model_key="openai-tts-1", voice_id="alloy")
    selection = resolve_voice_selection(preset, registry=_registry())
    assert secret not in repr(selection)
    assert secret not in repr(preset)

    missing = VoicePreset(id="q", model_key="elevenlabs-multilingual-v2", voice_id="rachel")
    with pytest.raises(ValidationError) as exc:
        resolve_voice_selection(missing, registry=_registry())
    assert secret not in str(exc.value)


# ------------------------- scene-specific use -------------------------


def test_same_preset_resolves_identically_for_different_scenes() -> None:
    preset = resolve_voice_preset(voice_preset_ids()[0])
    registry = _registry()
    a = resolve_voice_selection(preset, registry=registry, key_configured=_all_configured)
    b = resolve_voice_selection(preset, registry=registry, key_configured=_all_configured)
    assert a == b


def test_different_scenes_can_use_different_presets() -> None:
    registry = _registry()
    warm = VoicePreset(id="warm", model_key="openai-tts-1", voice_id="alloy")
    clear = VoicePreset(id="clear", model_key="qwen3-tts", voice_id="ko-clear")
    sel_a = resolve_voice_selection(warm, registry=registry, key_configured=_all_configured)
    sel_b = resolve_voice_selection(clear, registry=registry, key_configured=_all_configured)
    assert sel_a.model_key != sel_b.model_key
    assert sel_a.voice_id != sel_b.voice_id
