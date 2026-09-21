"""Pipeline quality control gate.

Validates render inputs before final FFmpeg render to catch pacing/quality issues
that would produce a poor video. Called just before render() in the pipeline.

Rules:
- Scene durations within min/max bounds
- Total duration within target range
- At least N scenes for visual variety
- No scene too short (causes jarring cuts)
- No scene too long (causes boredom)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PipelineQCResult:
    """Result of pipeline quality gate check."""

    passed: bool
    score: int  # 0-100
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    adjustments: dict[str, object] = field(default_factory=dict)


def validate_render_inputs(
    scene_durations: list[float],
    scene_count: int,
    total_duration: float | None = None,
    min_scenes: int = 5,
    max_scenes: int = 12,
    min_scene_duration: float = 3.0,
    max_scene_duration: float = 15.0,
    target_total_min: float = 30.0,
    target_total_max: float = 90.0,
) -> PipelineQCResult:
    """Validate render inputs against quality rules.

    Returns PipelineQCResult with pass/fail, issues, and suggested adjustments.
    """
    issues: list[str] = []
    warnings: list[str] = []
    adjustments: dict[str, object] = {}
    score = 100

    if total_duration is None:
        total_duration = sum(scene_durations)

    # Scene count checks
    if scene_count < min_scenes:
        issues.append(f"Too few scenes: {scene_count} (need at least {min_scenes})")
        score -= 20
    elif scene_count > max_scenes:
        warnings.append(f"Many scenes: {scene_count} (max recommended {max_scenes})")
        score -= 5

    # Total duration checks
    if total_duration < target_total_min:
        warnings.append(
            f"Video too short: {total_duration:.1f}s (target {target_total_min}-{target_total_max}s)"
        )
        score -= 10
    elif total_duration > target_total_max:
        warnings.append(
            f"Video too long: {total_duration:.1f}s (target {target_total_min}-{target_total_max}s)"
        )
        score -= 5

    # Per-scene duration checks
    adjusted_durations: list[float] = []
    for i, dur in enumerate(scene_durations):
        if dur < min_scene_duration:
            warnings.append(f"Scene {i + 1} too short: {dur:.1f}s (min {min_scene_duration}s)")
            adjusted_durations.append(min_scene_duration)
            score -= 3
        elif dur > max_scene_duration:
            warnings.append(f"Scene {i + 1} too long: {dur:.1f}s (max {max_scene_duration}s)")
            adjusted_durations.append(max_scene_duration)
            score -= 3
        else:
            adjusted_durations.append(dur)

    # If durations were adjusted, include them
    if adjusted_durations != scene_durations:
        adjustments["scene_durations"] = adjusted_durations

    # Pacing variance check — scenes shouldn't all be identical duration
    if len(scene_durations) >= 3:
        avg_dur = sum(scene_durations) / len(scene_durations)
        variance = sum((d - avg_dur) ** 2 for d in scene_durations) / len(scene_durations)
        if variance < 0.1:
            warnings.append("All scenes have nearly identical duration — video may feel robotic")
            score -= 5

    score = max(0, score)
    passed = score >= 50 and len(issues) == 0

    return PipelineQCResult(
        passed=passed,
        score=score,
        issues=issues,
        warnings=warnings,
        adjustments=adjustments,
    )
