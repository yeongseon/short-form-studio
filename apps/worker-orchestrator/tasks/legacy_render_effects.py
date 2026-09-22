from __future__ import annotations

import logging
from pathlib import Path
from subprocess import SubprocessError

from creator_domain.models.visual_plan import VisualPlan
from creator_service.bgm_service import bgm_service
from creator_service.ffmpeg_service import FFmpegService
from creator_service.recipe_profile import resolve_quality_profile
from tasks.legacy_render_audio import AudioInputs
from tasks.legacy_render_contract import LegacyRequest, LegacyServices

logger = logging.getLogger(__name__)
_OPTIONAL_FAILURES = (OSError, RuntimeError, ValueError, AttributeError, SubprocessError)


def climax_index(plan: VisualPlan | None, count: int) -> int:
    fallback = min(3, count - 2)
    if plan:
        for index, scene in enumerate(plan.scenes):
            if scene.section_type.lower() in ("climax", "body3"):
                return index if index < count else fallback
    return fallback


def mix_effects(request: LegacyRequest, inputs: AudioInputs, plan: VisualPlan | None) -> Path | None:
    audio = inputs.audio
    if audio is None:
        return None
    qp = resolve_quality_profile(request.profile_name)
    try:
        bgm = request.output("bgm.mp3")
        bgm_service.generate_ambient_bgm(sum(inputs.durations), str(bgm), mood=qp.bgm_mood)
        mixed = request.output("audio_mixed.mp3")
        bgm_service.mix_audio_with_bgm(str(audio), str(bgm), str(mixed), bgm_volume=qp.bgm_volume)
        audio = mixed
        if qp.sfx_enabled:
            try:
                cursor = 0.0
                timestamps: list[tuple[float, str]] = []
                for index, duration in enumerate(inputs.durations):
                    if index == 0:
                        timestamps.append((0.3, qp.sfx_hook_type))
                    elif index != len(inputs.durations) - 1:
                        timestamps.append((cursor - 0.1, qp.sfx_transition_type))
                    if index == climax_index(plan, len(inputs.durations)) and len(inputs.durations) >= 4:
                        timestamps.append((cursor + duration * 0.5, qp.sfx_climax_type))
                    cursor += duration
                audio = Path(bgm_service.mix_sfx_at_timestamps(
                    str(audio), timestamps, str(request.output("audio_sfx.mp3")), sfx_volume=qp.sfx_volume,
                ))
            except _OPTIONAL_FAILURES:
                logger.warning("SFX mixing failed for run %d", request.run_id, exc_info=True)
        if qp.loudnorm_enabled:
            try:
                audio = Path(bgm_service.normalize_loudness(
                    str(audio), str(request.output("audio_normalized.mp3")),
                    target_lufs=qp.loudnorm_target_lufs, true_peak=qp.loudnorm_true_peak,
                ))
            except _OPTIONAL_FAILURES:
                logger.warning("Loudness normalization failed for run %d", request.run_id, exc_info=True)
    except _OPTIONAL_FAILURES:
        logger.warning("BGM mixing failed for run %d, using original audio", request.run_id, exc_info=True)
    return audio


async def style_subtitles(
    request: LegacyRequest, services: LegacyServices, subtitle: Path | None,
    *, ffmpeg: FFmpegService,
) -> Path | None:
    if subtitle is None or subtitle.suffix != ".srt":
        return subtitle
    from tasks.script_qc import extract_emphasis_words

    try:
        qp = resolve_quality_profile(request.profile_name)
        words: list[str] | None = None
        if qp.subtitle_emphasis:
            draft = await services.scripts.get_active_draft(request.run_id)
            if draft and draft.markdown_content:
                words = extract_emphasis_words(draft.markdown_content)
        output = subtitle.with_suffix(".ass")
        ffmpeg.convert_srt_to_ass(str(subtitle), str(output), emphasis_words=words, emphasis_color=qp.emphasis_color)
        return output
    except _OPTIONAL_FAILURES:
        logger.warning("ASS conversion failed for run %d, using SRT", request.run_id, exc_info=True)
        return subtitle
