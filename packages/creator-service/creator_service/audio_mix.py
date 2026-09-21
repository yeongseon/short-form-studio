"""SF-62: deterministic AI audio-volume (mix) command translator and validator.

Audio mix is a RENDER-TIME concern (QualityProfile.bgm_volume fed to bgm_service),
NOT a Timeline edit — setAudio is an EditorCommand the Timeline applier rejects. So
this is a self-contained audio-mix domain, separate from EditorCommand /
CommandProposal / ProposalDiff / EditorHistory, never routed through
apply_editor_command. It mirrors the frontend MixSettings contract exactly
(music_volume, narration_volume, music_muted).

The canonical AudioMix self-validates its bounded [0,1] volumes so an invalid mix
can never exist. Requests target ONE track and change only that track's field,
leaving unrelated content untouched. Mute is a non-destructive flag (the stored
volume is preserved), and one shared resolver gives Preview/render mix consistency:
effective music volume is 0.0 when muted, else the stored volume. Relative louder/
quieter step by a fixed amount and clamp to the band (a no-op at the boundary, not
an error). Malformed requests raise a typed ValidationError.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal

from creator_domain.exceptions import ValidationError

VOLUME_STEP = 0.1

Track = Literal["music", "narration"]
CommandKind = Literal["set_volume", "set_muted"]
_ChangedField = Literal["music_volume", "narration_volume", "music_muted"]


def _validate_volume(volume: object, *, label: str) -> float:
    if not isinstance(volume, (int, float)) or isinstance(volume, bool):
        raise ValidationError(f"{label} volume must be a number")
    value = float(volume)
    if not math.isfinite(value):
        raise ValidationError(f"{label} volume must be finite")
    if value < 0.0 or value > 1.0:
        raise ValidationError(f"{label} volume must be within [0.0, 1.0]")
    return value


@dataclass(frozen=True)
class AudioMix:
    music_volume: float = 0.25
    narration_volume: float = 1.0
    music_muted: bool = False

    def __post_init__(self) -> None:
        # The canonical model enforces its own bounds so an invalid mix can never
        # exist to leak into the render/preview resolvers.
        _validate_volume(self.music_volume, label="music")
        _validate_volume(self.narration_volume, label="narration")
        if not isinstance(self.music_muted, bool):
            raise ValidationError("music_muted must be a boolean")


@dataclass(frozen=True)
class AudioMixCommand:
    track: Track
    kind: CommandKind
    value: float | bool

    def __post_init__(self) -> None:
        if self.track not in ("music", "narration"):
            raise ValidationError(f"unknown audio track: {self.track!r}")
        if self.kind == "set_muted":
            if self.track != "music":
                raise ValidationError("only the music track can be muted")
            if not isinstance(self.value, bool):
                raise ValidationError("muted value must be a boolean")
        elif self.kind == "set_volume":
            _validate_volume(self.value, label=self.track)
        else:
            raise ValidationError(f"unknown audio command kind: {self.kind!r}")


@dataclass(frozen=True)
class AudioMixDiff:
    before: AudioMix
    after: AudioMix
    changed_fields: tuple[_ChangedField, ...]


@dataclass(frozen=True)
class ResolvedAudioMix:
    music_volume: float
    narration_volume: float


def resolve_audio_mix(mix: AudioMix) -> ResolvedAudioMix:
    """Resolve stored mix state to the effective volumes preview and render share."""
    return ResolvedAudioMix(
        music_volume=0.0 if mix.music_muted else mix.music_volume,
        narration_volume=mix.narration_volume,
    )


def to_bgm_kwargs(mix: AudioMix) -> dict[str, float]:
    return {"bgm_volume": resolve_audio_mix(mix).music_volume}


def to_preview_mix(mix: AudioMix) -> dict[str, float]:
    resolved = resolve_audio_mix(mix)
    return {
        "music_volume": resolved.music_volume,
        "narration_volume": resolved.narration_volume,
    }


def _apply_command(mix: AudioMix, command: AudioMixCommand) -> AudioMix:
    if command.kind == "set_muted":
        return replace(mix, music_muted=bool(command.value))
    volume = float(command.value)
    if command.track == "music":
        return replace(mix, music_volume=volume)
    return replace(mix, narration_volume=volume)


def _clamp_volume(volume: float) -> float:
    return min(1.0, max(0.0, volume))


def translate_audio_mix_request(current: AudioMix, request: dict[str, object]) -> AudioMix:
    """Translate one mix request into a new AudioMix, changing only the targeted track.

    Exactly one directive (volume | relative | muted) against one track is required.
    Relative louder/quieter step by VOLUME_STEP and clamp to the band (no-op at the
    boundary). Mute applies only to music and preserves the stored volume. Unknown
    tracks/verbs/fields and empty/ambiguous/directive-less requests raise
    ValidationError.
    """
    if not isinstance(request, dict):
        raise ValidationError("audio mix request must be an object")
    if not request:
        raise ValidationError("audio mix request must not be empty")

    supported = {"track", "volume", "relative", "muted"}
    unsupported = set(request.keys()) - supported
    if unsupported:
        raise ValidationError(f"unsupported audio mix fields: {sorted(unsupported)}")

    track = request.get("track")
    if track not in ("music", "narration"):
        raise ValidationError(f"unknown audio track: {track!r}")

    directives = [key for key in ("volume", "relative", "muted") if key in request]
    if not directives:
        raise ValidationError("audio mix request must include a directive")
    if len(directives) != 1:
        raise ValidationError("audio mix request must have exactly one directive")
    directive = directives[0]

    if directive == "volume":
        volume = _validate_volume(request["volume"], label=str(track))
        command = AudioMixCommand(track=track, kind="set_volume", value=volume)
    elif directive == "relative":
        verb = request["relative"]
        if verb not in ("louder", "quieter"):
            raise ValidationError(f"unknown relative volume verb: {verb!r}")
        step = VOLUME_STEP if verb == "louder" else -VOLUME_STEP
        base = current.music_volume if track == "music" else current.narration_volume
        command = AudioMixCommand(
            track=track, kind="set_volume", value=_clamp_volume(base + step)
        )
    else:
        muted = request["muted"]
        if not isinstance(muted, bool):
            raise ValidationError("muted value must be a boolean")
        if track != "music":
            raise ValidationError("only the music track can be muted")
        command = AudioMixCommand(track=track, kind="set_muted", value=muted)

    return _apply_command(current, command)


def diff_audio_mix(before: AudioMix, after: AudioMix) -> AudioMixDiff:
    fields: tuple[_ChangedField, ...] = ("music_volume", "narration_volume", "music_muted")
    changed = tuple(f for f in fields if getattr(before, f) != getattr(after, f))
    return AudioMixDiff(before=before, after=after, changed_fields=changed)


@dataclass(frozen=True)
class AudioMixHistory:
    present: AudioMix
    past: tuple[AudioMix, ...] = field(default_factory=tuple)
    future: tuple[AudioMix, ...] = field(default_factory=tuple)

    def undo(self) -> AudioMixHistory:
        if not self.past:
            return self
        return AudioMixHistory(
            present=self.past[-1], past=self.past[:-1], future=(self.present, *self.future)
        )

    def redo(self) -> AudioMixHistory:
        if not self.future:
            return self
        return AudioMixHistory(
            present=self.future[0], past=(*self.past, self.present), future=self.future[1:]
        )


def apply_audio_mix(history: AudioMixHistory, command: AudioMixCommand) -> AudioMixHistory:
    """Apply a validated command as one undoable step; a no-op change pushes no history."""
    new_present = _apply_command(history.present, command)
    if new_present == history.present:
        return history
    return AudioMixHistory(
        present=new_present, past=(*history.past, history.present), future=()
    )


# SF-68: named reusable BGM/mix presets over the SF-62 levels-only model. Each preset
# is a validated AudioMix (levels only: music_volume / narration_volume / music_muted),
# so a preset structurally cannot replace the user's music asset — it carries no
# bgm_path. The same resolved effective volumes feed preview and the renderer's
# ducking, so presets stay compatible with existing ducking without touching it.
AUDIO_MIX_PRESETS: dict[str, AudioMix] = {
    "balanced": AudioMix(),
    "music_forward": AudioMix(music_volume=0.5, narration_volume=0.9),
    "voice_focused": AudioMix(music_volume=0.12, narration_volume=1.0),
    "muted_music": AudioMix(music_volume=0.25, narration_volume=1.0, music_muted=True),
}


def audio_mix_preset_ids() -> tuple[str, ...]:
    """Return the shipped BGM/mix preset ids, sorted."""
    return tuple(sorted(AUDIO_MIX_PRESETS))


def resolve_audio_mix_preset(preset_id: str) -> AudioMix:
    """Resolve a named BGM/mix preset; unknown or non-string ids raise."""
    if not isinstance(preset_id, str) or preset_id not in AUDIO_MIX_PRESETS:
        raise ValidationError(f"unknown audio mix preset: {preset_id!r}")
    return AUDIO_MIX_PRESETS[preset_id]


def apply_audio_mix_preset(history: AudioMixHistory, preset_id: str) -> AudioMixHistory:
    """Select a preset as one full-state undoable step; a preset equal to the present is a no-op."""
    preset = resolve_audio_mix_preset(preset_id)
    if preset == history.present:
        return history
    return AudioMixHistory(
        present=preset, past=(*history.past, history.present), future=()
    )
