from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import SubprocessError

from creator_service.ffmpeg_service import FFmpegService
from tasks.legacy_render_contract import LegacyManifest, LegacyRequest, LegacyServices


@dataclass(frozen=True, slots=True)
class AudioInputs:
    audio: Path | None
    subtitles: Path | None
    durations: list[float]


def compute_scene_durations(
    ffmpeg: FFmpegService, audio_path: Path | None,
    scene_count: int, max_duration_seconds: float,
) -> list[float]:
    total = max_duration_seconds
    if audio_path:
        try:
            total = ffmpeg.get_audio_duration(str(audio_path))
        except (OSError, RuntimeError, ValueError, KeyError, SubprocessError):
            total = max_duration_seconds
    return [total / scene_count] * scene_count


async def prepare_audio(
    request: LegacyRequest, services: LegacyServices, manifest: LegacyManifest,
    *, ffmpeg: FFmpegService,
) -> AudioInputs:
    run_audio = request.path(manifest.audio_path) if manifest.audio_path else None
    run_subs = request.path(manifest.subtitle_path) if manifest.subtitle_path else None
    paragraph_audio = await services.audio.list_paragraph_audio(request.run_id)
    paragraph_subtitles = await services.subtitles.list_paragraph_subtitles(request.run_id)
    audio_by_section = {}
    for artifact in paragraph_audio:
        if artifact.section_id and artifact.section_id not in audio_by_section:
            audio_by_section[artifact.section_id] = artifact
    draft = await services.scripts.get_active_draft(request.run_id) if paragraph_audio else None
    ordered = (
        [section.section_id for section in draft.structured_script]
        if draft and draft.structured_script else list(audio_by_section)
    )
    if not ordered or not all(section in audio_by_section for section in ordered):
        return AudioInputs(run_audio, run_subs, compute_scene_durations(
            ffmpeg, run_audio, len(manifest.scenes), manifest.render_profile.max_duration_seconds,
        ))
    audio_paths = {section: str(request.path(audio_by_section[section].path)) for section in ordered}
    durations: dict[str, float] = {}
    for section in ordered:
        try:
            durations[section] = ffmpeg.get_audio_duration(audio_paths[section])
        except (OSError, RuntimeError, ValueError, KeyError, SubprocessError):
            durations[section] = 5.0
    audio = request.output("audio_concat.wav")
    ffmpeg.concatenate_audio([audio_paths[section] for section in ordered], str(audio))
    scene_durations = [durations[section] for section in ordered][:len(manifest.scenes)]
    scene_durations.extend([5.0] * (len(manifest.scenes) - len(scene_durations)))
    subs_by_section = {s.section_id: s for s in reversed(paragraph_subtitles) if s.section_id}
    subtitles = run_subs
    if all(section in subs_by_section for section in ordered):
        subtitles = request.output("subtitles_merged.srt")
        ffmpeg.merge_subtitles(
            [str(request.path(subs_by_section[section].path)) for section in ordered],
            [durations[section] for section in ordered], str(subtitles),
        )
    return AudioInputs(audio, subtitles, scene_durations)
