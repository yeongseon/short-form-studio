"""SF-67: reusable voice presets for short drafts (provider/voice/settings).

A VoicePreset is a reusable, CREDENTIAL-FREE selection of a TTS model_key + voice_id
+ provider-agnostic settings, independent of recipes. It carries NO api key, secret,
or endpoint — credentials stay in the environment (resolve_api_key) and are never
embedded in a preset, a resolved selection, or an error. resolve_voice_selection
derives the provider from ProviderRegistry.resolve(model_key) (requiring a TTS
model), and reports availability by checking configured-ness of a remote provider's
key as a boolean only — the key VALUE is never read into a result or message.
Unsupported (unknown/non-TTS model, or a remote provider with no credential mapping)
and missing-provider (remote key not configured) produce distinct typed errors.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from creator_domain.exceptions import ValidationError
from creator_provider.api_keys import resolve_api_key
from creator_provider.registry import ProviderCategory, ProviderRegistry

_SettingValue = str | int | float | bool

# Remote TTS provider_type -> api_keys provider name. A remote model whose provider
# is absent here has no safe way to check credential presence, so it is rejected
# rather than treated as keyless.
_PROVIDER_KEY_NAME: dict[str, str] = {
    "openai_tts": "openai",
    "elevenlabs_tts": "elevenlabs",
}
_ENV_VAR_FOR_PROVIDER: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}


def _validate_setting_value(key: object, value: object) -> None:
    if not isinstance(key, str) or not key:
        raise ValidationError("voice preset setting keys must be non-empty strings")
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValidationError(f"voice preset setting {key!r} must be finite")
        return
    if isinstance(value, str):
        return
    raise ValidationError(f"voice preset setting {key!r} must be a primitive value")


@dataclass(frozen=True)
class VoicePreset:
    id: str
    model_key: str
    voice_id: str
    settings: Mapping[str, _SettingValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label in ("id", "model_key", "voice_id"):
            value = getattr(self, label)
            if not isinstance(value, str) or not value:
                raise ValidationError(f"voice preset {label} must be a non-empty string")
        if not isinstance(self.settings, Mapping):
            raise ValidationError("voice preset settings must be a mapping")
        for key, value in self.settings.items():
            _validate_setting_value(key, value)
        # Freeze settings so a preset's selection cannot be mutated through it.
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))


@dataclass(frozen=True)
class ResolvedVoiceSelection:
    preset_id: str
    model_key: str
    provider_type: str
    voice_id: str
    settings: Mapping[str, _SettingValue]


VOICE_PRESETS: dict[str, VoicePreset] = {
    "narration_clear": VoicePreset(
        id="narration_clear", model_key="qwen3-tts", voice_id="ko-clear",
        settings={"rate": "+0%"},
    ),
    "narration_warm": VoicePreset(
        id="narration_warm", model_key="openai-tts-1", voice_id="alloy",
        settings={"speed": 1.0},
    ),
    "narration_expressive": VoicePreset(
        id="narration_expressive", model_key="elevenlabs-multilingual-v2", voice_id="rachel",
        settings={"stability": 0.5, "style": 0.4},
    ),
}


def voice_preset_ids() -> tuple[str, ...]:
    """Return the shipped voice preset ids, sorted."""
    return tuple(sorted(VOICE_PRESETS))


def resolve_voice_preset(preset_id: str) -> VoicePreset:
    """Resolve a named voice preset; unknown, blank, or non-string ids raise."""
    if not isinstance(preset_id, str) or preset_id not in VOICE_PRESETS:
        raise ValidationError(f"unknown voice preset: {preset_id!r}")
    return VOICE_PRESETS[preset_id]


def resolve_voice_selection(
    preset: VoicePreset,
    *,
    registry: ProviderRegistry,
    key_configured: Callable[[str], bool] | None = None,
) -> ResolvedVoiceSelection:
    """Resolve a preset to a credential-free provider/voice/settings selection.

    The model is resolved through the registry and must be a TTS model (unknown or
    non-TTS -> unsupported error). A remote model requires a known credential
    mapping and a configured key; a missing key is a distinct missing-provider error
    that names only the env var guidance, never the key value. No provider is
    instantiated and no key value is ever read into the result or an error.
    """
    try:
        entry = registry.resolve(preset.model_key)
    except KeyError as error:
        raise ValidationError(
            f"voice model {preset.model_key!r} is not supported (unknown model)"
        ) from error
    if entry.category != ProviderCategory.TTS:
        raise ValidationError(
            f"voice model {preset.model_key!r} is not a voice (TTS) model"
        )

    if not entry.is_local:
        provider_name = _PROVIDER_KEY_NAME.get(entry.provider_type)
        if provider_name is None:
            raise ValidationError(
                f"remote voice provider {entry.provider_type!r} has no credential "
                f"resolver configured and is not supported"
            )
        checker = key_configured if key_configured is not None else _default_key_configured
        if not checker(provider_name):
            env_var = _ENV_VAR_FOR_PROVIDER.get(provider_name, f"{provider_name.upper()}_API_KEY")
            raise ValidationError(
                f"voice provider {entry.provider_type!r} is not configured; "
                f"set the {env_var} environment variable"
            )

    return ResolvedVoiceSelection(
        preset_id=preset.id,
        model_key=preset.model_key,
        provider_type=entry.provider_type,
        voice_id=preset.voice_id,
        settings=preset.settings,
    )


def _default_key_configured(provider_name: str) -> bool:
    return resolve_api_key(provider_name, required=False) is not None
