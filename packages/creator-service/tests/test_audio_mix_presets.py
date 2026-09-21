"""SF-68: reusable BGM/mix presets applied through the shared audio-mix state.

Presets are named, validated AudioMix instances over the SF-62 levels-only model —
music_volume / narration_volume / music_muted, and NOTHING else. Because the model
carries no bgm_path, asset id, mood, or ducking parameter, applying a preset is
structurally incapable of replacing the user's chosen music: it only changes mix
LEVELS. Selecting a preset is one full-state undoable step on the shared
AudioMixHistory, the same resolved effective volumes feed both preview and the
renderer's ducking (via to_bgm_kwargs / to_preview_mix), and a preset equal to the
current state is a no-op. Unknown/non-string preset ids raise a typed ValidationError.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_service.audio_mix import (
    AUDIO_MIX_PRESETS,
    AudioMix,
    AudioMixHistory,
    apply_audio_mix_preset,
    audio_mix_preset_ids,
    resolve_audio_mix,
    resolve_audio_mix_preset,
    to_bgm_kwargs,
    to_preview_mix,
)


# ------------------------- registry validity + ids -------------------------


def test_every_preset_is_a_valid_audio_mix() -> None:
    assert AUDIO_MIX_PRESETS
    for mix in AUDIO_MIX_PRESETS.values():
        assert isinstance(mix, AudioMix)


def test_balanced_preset_equals_the_default_mix() -> None:
    assert AUDIO_MIX_PRESETS["balanced"] == AudioMix()


def test_preset_ids_are_a_sorted_immutable_tuple() -> None:
    ids = audio_mix_preset_ids()
    assert isinstance(ids, tuple)
    assert list(ids) == sorted(AUDIO_MIX_PRESETS)


def test_resolve_returns_the_registered_preset() -> None:
    assert resolve_audio_mix_preset("music_forward") == AUDIO_MIX_PRESETS["music_forward"]


def test_resolve_rejects_unknown_preset_id() -> None:
    with pytest.raises(ValidationError, match="preset"):
        resolve_audio_mix_preset("thunderous")


@pytest.mark.parametrize("bad", [None, 123, True, ["balanced"]])
def test_resolve_rejects_non_string_preset_id(bad: object) -> None:
    with pytest.raises(ValidationError, match="preset"):
        resolve_audio_mix_preset(bad)  # type: ignore[arg-type]


# ------------------------- narration/music balance -------------------------


def test_music_forward_has_higher_effective_music_than_balanced() -> None:
    balanced = resolve_audio_mix(resolve_audio_mix_preset("balanced"))
    forward = resolve_audio_mix(resolve_audio_mix_preset("music_forward"))
    assert forward.music_volume > balanced.music_volume


def test_voice_focused_has_lower_effective_music_than_balanced() -> None:
    balanced = resolve_audio_mix(resolve_audio_mix_preset("balanced"))
    focused = resolve_audio_mix(resolve_audio_mix_preset("voice_focused"))
    assert focused.music_volume < balanced.music_volume


def test_muted_music_preset_resolves_effective_music_to_zero() -> None:
    resolved = resolve_audio_mix(resolve_audio_mix_preset("muted_music"))
    assert resolved.music_volume == pytest.approx(0.0)
    assert resolved.narration_volume > 0.0


# ------------------------- preview/render consistency -------------------------


@pytest.mark.parametrize("preset_id", ["balanced", "music_forward", "voice_focused", "muted_music"])
def test_preview_and_render_share_the_same_effective_music_volume(preset_id: str) -> None:
    mix = resolve_audio_mix_preset(preset_id)
    assert to_bgm_kwargs(mix)["bgm_volume"] == pytest.approx(
        to_preview_mix(mix)["music_volume"]
    )


@pytest.mark.parametrize("preset_id", ["balanced", "music_forward", "voice_focused", "muted_music"])
def test_every_preset_produces_a_ducking_compatible_bgm_volume(preset_id: str) -> None:
    # The renderer's ducking filter clamps bgm_volume to [0,1]; every preset must
    # already resolve to a finite in-band value so the preset feeds ducking cleanly.
    import math

    bgm_volume = to_bgm_kwargs(resolve_audio_mix_preset(preset_id))["bgm_volume"]
    assert math.isfinite(bgm_volume)
    assert 0.0 <= bgm_volume <= 1.0


# ------------------------- shared-state apply + undo -------------------------


def test_applying_a_preset_is_one_full_state_undoable_step() -> None:
    history = AudioMixHistory(present=AudioMix())
    a = apply_audio_mix_preset(history, "music_forward")
    assert a.present == AUDIO_MIX_PRESETS["music_forward"]
    assert a.past == (AudioMix(),)

    b = apply_audio_mix_preset(a, "voice_focused")
    assert b.present == AUDIO_MIX_PRESETS["voice_focused"]

    reverted = b.undo()
    assert reverted.present == AUDIO_MIX_PRESETS["music_forward"]


def test_applying_a_preset_clears_the_redo_branch() -> None:
    history = AudioMixHistory(present=AudioMix())
    a = apply_audio_mix_preset(history, "music_forward")
    b = apply_audio_mix_preset(a, "voice_focused")
    diverged = apply_audio_mix_preset(b.undo(), "muted_music")
    assert diverged.future == ()
    assert diverged.present == AUDIO_MIX_PRESETS["muted_music"]


def test_applying_a_preset_equal_to_the_present_is_a_noop() -> None:
    history = AudioMixHistory(present=AUDIO_MIX_PRESETS["music_forward"])
    same = apply_audio_mix_preset(history, "music_forward")
    assert same.past == ()
    assert same is history


def test_apply_preset_rejects_an_unknown_id() -> None:
    history = AudioMixHistory(present=AudioMix())
    with pytest.raises(ValidationError, match="preset"):
        apply_audio_mix_preset(history, "thunderous")


# ------------------------- no media replacement -------------------------


def test_a_preset_carries_only_mix_levels_and_no_media_reference() -> None:
    # AudioMix is levels-only, so a preset structurally cannot replace the user's
    # chosen music asset — it has no bgm_path / asset / source field.
    for forbidden in ("bgm_path", "asset_id", "source", "path", "mood", "bgm_mood"):
        assert not hasattr(AUDIO_MIX_PRESETS["balanced"], forbidden)


def test_applying_a_preset_changes_only_mix_level_fields() -> None:
    history = AudioMixHistory(present=AudioMix(music_volume=0.3, narration_volume=0.8))
    applied = apply_audio_mix_preset(history, "muted_music")
    changed = applied.present
    # only the three mix-level fields exist and may change; nothing else
    assert set(vars(changed)) == {"music_volume", "narration_volume", "music_muted"}
