from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    class StrEnum(Enum):
        ...
else:
    try:
        from enum import StrEnum
    except ImportError:
        StrEnum = Enum("StrEnum", {}, type=str)


class RunStage(StrEnum):
    IDEA_READY = "IDEA_READY"
    SCRIPT_GENERATING = "SCRIPT_GENERATING"
    SCRIPT_REVIEW = "SCRIPT_REVIEW"
    VISUAL_PLAN_GENERATING = "VISUAL_PLAN_GENERATING"
    VISUAL_PLAN_REVIEW = "VISUAL_PLAN_REVIEW"
    VISUAL_ASSET_GENERATING = "VISUAL_ASSET_GENERATING"
    VISUAL_ASSET_REVIEW = "VISUAL_ASSET_REVIEW"
    AUDIO_GENERATING = "AUDIO_GENERATING"
    SUBTITLE_GENERATING = "SUBTITLE_GENERATING"
    RENDER_GENERATING = "RENDER_GENERATING"
    FINAL_REVIEW = "FINAL_REVIEW"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


TRANSITIONS: dict[RunStage, tuple[RunStage, ...]] = {
    RunStage.IDEA_READY: (RunStage.SCRIPT_GENERATING,),
    RunStage.SCRIPT_GENERATING: (RunStage.SCRIPT_REVIEW, RunStage.FAILED),
    RunStage.SCRIPT_REVIEW: (RunStage.VISUAL_PLAN_GENERATING, RunStage.SCRIPT_GENERATING),
    RunStage.VISUAL_PLAN_GENERATING: (RunStage.VISUAL_PLAN_REVIEW, RunStage.FAILED),
    RunStage.VISUAL_PLAN_REVIEW: (RunStage.VISUAL_ASSET_GENERATING, RunStage.VISUAL_PLAN_GENERATING),
    RunStage.VISUAL_ASSET_GENERATING: (RunStage.VISUAL_ASSET_REVIEW, RunStage.FAILED),
    RunStage.VISUAL_ASSET_REVIEW: (RunStage.AUDIO_GENERATING, RunStage.VISUAL_ASSET_GENERATING),
    RunStage.AUDIO_GENERATING: (RunStage.SUBTITLE_GENERATING, RunStage.FAILED),
    RunStage.SUBTITLE_GENERATING: (RunStage.RENDER_GENERATING, RunStage.FAILED),
    RunStage.RENDER_GENERATING: (RunStage.FINAL_REVIEW, RunStage.FAILED),
    RunStage.FINAL_REVIEW: (RunStage.PUBLISHED, RunStage.RENDER_GENERATING),
    RunStage.PUBLISHED: (),
    RunStage.FAILED: (),
}


REVIEW_STAGES: frozenset[RunStage] = frozenset(
    {
        RunStage.SCRIPT_REVIEW,
        RunStage.VISUAL_PLAN_REVIEW,
        RunStage.VISUAL_ASSET_REVIEW,
        RunStage.FINAL_REVIEW,
    }
)

GENERATING_STAGES: frozenset[RunStage] = frozenset(
    {
        RunStage.SCRIPT_GENERATING,
        RunStage.VISUAL_PLAN_GENERATING,
        RunStage.VISUAL_ASSET_GENERATING,
        RunStage.AUDIO_GENERATING,
        RunStage.SUBTITLE_GENERATING,
        RunStage.RENDER_GENERATING,
    }
)


def can_transition(current: RunStage, target: RunStage) -> bool:
    return target in TRANSITIONS[current]


def next_stages(current: RunStage) -> list[RunStage]:
    return list(TRANSITIONS[current])


def advance(current: RunStage) -> RunStage:
    candidates = [stage for stage in TRANSITIONS[current] if stage is not RunStage.FAILED]
    if len(candidates) != 1:
        raise ValueError(f"Stage {current} does not have exactly one non-failed transition")
    return candidates[0]
