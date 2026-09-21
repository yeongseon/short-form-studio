"""SF-62: deterministic AI audio-volume (mix) command translator and validator.

Audio mix is a RENDER-TIME concern (QualityProfile.bgm_volume fed to bgm_service),
NOT a Timeline edit — setAudio is an EditorCommand the Timeline applier rejects. So
this is a self-contained audio-mix domain, separate from EditorCommand /
CommandProposal / ProposalDiff / EditorHistory, never routed through
apply_editor_command. It mirrors the frontend MixSettings contract exactly
(music_volume, narration_volume, music_muted).

The canonical AudioMix self-validates its bounded [0,1] volumes. Requests target ONE
track and change only that track's field, leaving unrelated content untouched. Mute
is a non-destructive flag (stored volume preserved), and a single shared resolver
gives Preview/render mix consistency: effective music volume is 0.0 when muted, else
the stored volume. Relative louder/quieter step by a fixed amount and clamp to the
band (a no-op at the boundary). Malformed requests raise a typed ValidationError.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_service.audio_mix import (
    VOLUME_STEP,
    AudioMix,
    AudioMixCommand,
    AudioMixDiff,
    AudioMixHistory,
    apply_audio_mix,
    diff_audio_mix,
    resolve_audio_mix,
    to_bgm_kwargs,
    to_preview_mix,
    translate_audio_mix_request,
)


def test_default_mix_matches_the_established_contract() -> None:
    mix = AudioMix()
    assert mix.music_volume == pytest.approx(0.25)
    assert mix.narration_volume == pytest.approx(1.0)
    assert mix.music_muted is False


@pytest.mark.parametrize("volume", [0.0, 1.0, 0.5])
def test_boundary_and_mid_volumes_are_accepted(volume: float) -> None:
    mix = AudioMix(music_volume=volume, narration_volume=volume)
    assert mix.music_volume == pytest.approx(volume)
    assert mix.narration_volume == pytest.approx(volume)


@pytest.mark.parametrize("bad", [-0.01, 1.01, float("nan"), float("inf"), float("-inf")])
def test_rejects_out_of_band_or_non_finite_volume(bad: float) -> None:
    with pytest.raises(ValidationError, match="volume"):
        AudioMix(music_volume=bad)
    with pytest.raises(ValidationError, match="volume"):
        AudioMix(narration_volume=bad)


def test_rejects_boolean_volume_which_is_not_a_real_level() -> None:
    with pytest.raises(ValidationError, match="volume"):
        AudioMix(music_volume=True)  # type: ignore[arg-type]


def test_set_music_volume_targets_only_music() -> None:
    result = translate_audio_mix_request(AudioMix(), {"track": "music", "volume": 0.5})
    assert result.music_volume == pytest.approx(0.5)
    assert result.narration_volume == pytest.approx(1.0)
    assert result.music_muted is False


def test_set_narration_volume_targets_only_narration() -> None:
    result = translate_audio_mix_request(AudioMix(), {"track": "narration", "volume": 0.8})
    assert result.narration_volume == pytest.approx(0.8)
    assert result.music_volume == pytest.approx(0.25)


def test_mute_music_targets_only_the_mute_flag_preserving_volume() -> None:
    # Mute is non-destructive: it sets music_muted only and preserves the stored
    # music_volume so unmute restores it, and never touches narration.
    result = translate_audio_mix_request(AudioMix(), {"track": "music", "muted": True})
    assert result.music_muted is True
    assert result.music_volume == pytest.approx(0.25)
    assert result.narration_volume == pytest.approx(1.0)


def test_relative_louder_and_quieter_step_by_fixed_amount() -> None:
    louder = translate_audio_mix_request(AudioMix(), {"track": "music", "relative": "louder"})
    assert louder.music_volume == pytest.approx(0.25 + VOLUME_STEP)
    quieter = translate_audio_mix_request(AudioMix(), {"track": "music", "relative": "quieter"})
    assert quieter.music_volume == pytest.approx(0.25 - VOLUME_STEP)


def test_relative_louder_at_max_clamps_to_one_as_noop() -> None:
    maxed = AudioMix(music_volume=1.0)
    result = translate_audio_mix_request(maxed, {"track": "music", "relative": "louder"})
    assert result.music_volume == pytest.approx(1.0)


def test_relative_quieter_at_zero_clamps_to_zero_as_noop() -> None:
    zeroed = AudioMix(music_volume=0.0)
    result = translate_audio_mix_request(zeroed, {"track": "music", "relative": "quieter"})
    assert result.music_volume == pytest.approx(0.0)


def test_muted_music_resolves_to_zero_effective_volume() -> None:
    resolved = resolve_audio_mix(AudioMix(music_volume=0.8, music_muted=True))
    assert resolved.music_volume == pytest.approx(0.0)
    assert resolved.narration_volume == pytest.approx(1.0)


def test_unmuting_restores_the_stored_music_volume() -> None:
    muted = AudioMix(music_volume=0.8, music_muted=True)
    unmuted = translate_audio_mix_request(muted, {"track": "music", "muted": False})
    assert unmuted.music_muted is False
    assert resolve_audio_mix(unmuted).music_volume == pytest.approx(0.8)


def test_preview_and_render_helpers_use_the_same_effective_volumes() -> None:
    # Preview/render mix consistency: the SAME AudioMix resolves to the SAME
    # effective volumes for both surfaces, including when music is muted.
    mix = AudioMix(music_volume=0.6, narration_volume=0.9, music_muted=True)
    resolved = resolve_audio_mix(mix)
    assert to_bgm_kwargs(mix) == {"bgm_volume": resolved.music_volume}
    assert to_bgm_kwargs(mix)["bgm_volume"] == pytest.approx(0.0)
    preview = to_preview_mix(mix)
    assert preview["music_volume"] == pytest.approx(resolved.music_volume)
    assert preview["narration_volume"] == pytest.approx(resolved.narration_volume)


def test_to_bgm_kwargs_uses_stored_volume_when_unmuted() -> None:
    assert to_bgm_kwargs(AudioMix(music_volume=0.4))["bgm_volume"] == pytest.approx(0.4)


def test_diff_reports_exact_changed_fields() -> None:
    before = AudioMix()
    after = AudioMix(music_volume=0.5)
    diff = diff_audio_mix(before, after)
    assert isinstance(diff, AudioMixDiff)
    assert diff.before == before
    assert diff.after == after
    assert diff.changed_fields == ("music_volume",)


def test_diff_of_identical_mix_has_no_changed_fields() -> None:
    mix = AudioMix()
    assert diff_audio_mix(mix, mix).changed_fields == ()


def test_apply_pushes_history_and_undo_restores_exactly() -> None:
    history = AudioMixHistory(present=AudioMix())
    command = AudioMixCommand(track="music", kind="set_volume", value=0.5)
    applied = apply_audio_mix(history, command)
    assert applied.present.music_volume == pytest.approx(0.5)
    assert applied.past == (AudioMix(),)
    reverted = applied.undo()
    assert reverted.present == AudioMix()
    assert reverted.future == (AudioMix(music_volume=0.5),)


def test_redo_reapplies_the_undone_mix() -> None:
    history = AudioMixHistory(present=AudioMix())
    applied = apply_audio_mix(history, AudioMixCommand(track="music", kind="set_volume", value=0.5))
    redone = applied.undo().redo()
    assert redone.present.music_volume == pytest.approx(0.5)


def test_apply_after_undo_clears_the_redo_branch() -> None:
    history = AudioMixHistory(present=AudioMix())
    applied = apply_audio_mix(history, AudioMixCommand(track="music", kind="set_volume", value=0.5))
    diverged = apply_audio_mix(
        applied.undo(), AudioMixCommand(track="narration", kind="set_volume", value=0.4)
    )
    assert diverged.future == ()
    assert diverged.present.narration_volume == pytest.approx(0.4)


def test_applying_a_noop_command_does_not_push_history() -> None:
    # A command that lands the same value (e.g. re-setting the current volume) is
    # a no-op: it produces no history entry so undo is not polluted with no-ops.
    history = AudioMixHistory(present=AudioMix(music_volume=0.5))
    same = apply_audio_mix(history, AudioMixCommand(track="music", kind="set_volume", value=0.5))
    assert same.past == ()
    assert same.present == AudioMix(music_volume=0.5)


def test_apply_never_touches_timeline_state() -> None:
    history = AudioMixHistory(present=AudioMix())
    applied = apply_audio_mix(history, AudioMixCommand(track="music", kind="set_volume", value=0.6))
    assert not hasattr(applied, "segments")


def test_rejects_muting_narration_which_is_the_base_track() -> None:
    with pytest.raises(ValidationError, match="narration|mute"):
        translate_audio_mix_request(AudioMix(), {"track": "narration", "muted": True})


def test_rejects_unknown_track() -> None:
    with pytest.raises(ValidationError, match="track"):
        translate_audio_mix_request(AudioMix(), {"track": "sfx", "volume": 0.5})


def test_rejects_unknown_relative_verb() -> None:
    with pytest.raises(ValidationError, match="relative"):
        translate_audio_mix_request(AudioMix(), {"track": "music", "relative": "crankit"})


def test_rejects_unsupported_field() -> None:
    with pytest.raises(ValidationError, match="unsupported|unknown"):
        translate_audio_mix_request(AudioMix(), {"track": "music", "pan": 0.5})


def test_rejects_empty_request() -> None:
    with pytest.raises(ValidationError, match="empty|request"):
        translate_audio_mix_request(AudioMix(), {})


def test_rejects_request_without_a_directive() -> None:
    with pytest.raises(ValidationError, match="directive"):
        translate_audio_mix_request(AudioMix(), {"track": "music"})


def test_rejects_ambiguous_request_with_multiple_directives() -> None:
    with pytest.raises(ValidationError, match="one|ambiguous|exactly"):
        translate_audio_mix_request(
            AudioMix(), {"track": "music", "volume": 0.5, "muted": True}
        )


def test_rejects_non_dict_request() -> None:
    with pytest.raises(ValidationError, match="object|request"):
        translate_audio_mix_request(AudioMix(), ["track", "music"])  # type: ignore[arg-type]


def test_rejects_non_bool_muted_value() -> None:
    with pytest.raises(ValidationError, match="muted"):
        translate_audio_mix_request(AudioMix(), {"track": "music", "muted": "yes"})


def test_command_rejects_set_muted_on_narration() -> None:
    with pytest.raises(ValidationError, match="narration|mute"):
        AudioMixCommand(track="narration", kind="set_muted", value=True)


def test_command_rejects_out_of_band_volume() -> None:
    with pytest.raises(ValidationError, match="volume"):
        AudioMixCommand(track="music", kind="set_volume", value=1.5)
