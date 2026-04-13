from __future__ import annotations

import sys
from enum import Enum

if sys.version_info >= (3, 11):  # noqa: UP036
    from enum import StrEnum
else:

    class StrEnum(str, Enum):  # noqa: UP042
        def __str__(self) -> str:
            return self.value

class RunStage(StrEnum):
    IDEA_READY = "IDEA_READY"
    SCRIPT_GENERATING = "SCRIPT_GENERATING"
    SCRIPT_REVIEW = "SCRIPT_REVIEW"
    VISUAL_PLAN_SETUP = "VISUAL_PLAN_SETUP"
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


TRIGGER_POLICY: dict[str, frozenset[RunStage]] = {
    "generate_script": frozenset({RunStage.IDEA_READY, RunStage.SCRIPT_REVIEW, RunStage.SCRIPT_GENERATING}),
    "generate_visual_plan": frozenset({RunStage.VISUAL_PLAN_SETUP, RunStage.VISUAL_PLAN_GENERATING}),
    "generate_visual_assets": frozenset({RunStage.VISUAL_PLAN_REVIEW, RunStage.VISUAL_ASSET_GENERATING, RunStage.VISUAL_ASSET_REVIEW}),
    "generate_audio": frozenset({RunStage.VISUAL_ASSET_REVIEW, RunStage.AUDIO_GENERATING}),
    "render_video": frozenset({RunStage.RENDER_GENERATING}),
}


TRANSITIONS: dict[RunStage, tuple[RunStage, ...]] = {
    RunStage.IDEA_READY: (RunStage.SCRIPT_GENERATING,),
    RunStage.SCRIPT_GENERATING: (RunStage.SCRIPT_REVIEW, RunStage.FAILED),
    RunStage.SCRIPT_REVIEW: (RunStage.VISUAL_PLAN_SETUP, RunStage.SCRIPT_GENERATING),
    RunStage.VISUAL_PLAN_SETUP: (RunStage.VISUAL_PLAN_GENERATING,),
    RunStage.VISUAL_PLAN_GENERATING: (RunStage.VISUAL_PLAN_REVIEW, RunStage.FAILED),
    RunStage.VISUAL_PLAN_REVIEW: (RunStage.VISUAL_ASSET_GENERATING, RunStage.VISUAL_PLAN_GENERATING),
    RunStage.VISUAL_ASSET_GENERATING: (RunStage.VISUAL_ASSET_REVIEW, RunStage.FAILED),
    RunStage.VISUAL_ASSET_REVIEW: (RunStage.AUDIO_GENERATING, RunStage.VISUAL_ASSET_GENERATING),
    RunStage.AUDIO_GENERATING: (RunStage.SUBTITLE_GENERATING, RunStage.FAILED),
    RunStage.SUBTITLE_GENERATING: (RunStage.RENDER_GENERATING, RunStage.FAILED),
    RunStage.RENDER_GENERATING: (RunStage.FINAL_REVIEW, RunStage.FAILED),
    RunStage.FINAL_REVIEW: (RunStage.PUBLISHED, RunStage.RENDER_GENERATING),
    RunStage.PUBLISHED: (),
    RunStage.FAILED: (RunStage.SCRIPT_GENERATING, RunStage.VISUAL_PLAN_GENERATING, RunStage.VISUAL_ASSET_GENERATING, RunStage.AUDIO_GENERATING, RunStage.SUBTITLE_GENERATING, RunStage.RENDER_GENERATING),
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


# Maps each GENERATING stage to the actionable stage the user returns to on stop.

# Used by stop_run to move current_stage out of GENERATING so worker CAS fails.

# For storyboard stages (audio/subtitle/render), all roll back to

# VISUAL_ASSET_REVIEW — the last user-actionable review stage.

STAGE_BEFORE_GENERATING: dict[RunStage, RunStage] = {

    RunStage.SCRIPT_GENERATING: RunStage.IDEA_READY,

    RunStage.VISUAL_PLAN_GENERATING: RunStage.VISUAL_PLAN_SETUP,

    RunStage.VISUAL_ASSET_GENERATING: RunStage.VISUAL_PLAN_REVIEW,

    RunStage.AUDIO_GENERATING: RunStage.VISUAL_ASSET_REVIEW,

    RunStage.SUBTITLE_GENERATING: RunStage.VISUAL_ASSET_REVIEW,

    RunStage.RENDER_GENERATING: RunStage.VISUAL_ASSET_REVIEW,

}
STAGE_BACK: dict[RunStage, RunStage] = {
    RunStage.SCRIPT_REVIEW: RunStage.IDEA_READY,
    RunStage.VISUAL_PLAN_SETUP: RunStage.SCRIPT_REVIEW,
    RunStage.VISUAL_PLAN_REVIEW: RunStage.VISUAL_PLAN_SETUP,
    RunStage.VISUAL_ASSET_REVIEW: RunStage.VISUAL_PLAN_REVIEW,
    RunStage.FINAL_REVIEW: RunStage.VISUAL_ASSET_REVIEW,
}



def can_transition(current: RunStage, target: RunStage) -> bool:
    return target in TRANSITIONS[current]


def next_stages(current: RunStage) -> list[RunStage]:
    return list(TRANSITIONS[current])


def advance(current: RunStage) -> RunStage:
    candidates = [stage for stage in TRANSITIONS[current] if stage is not RunStage.FAILED]
    if len(candidates) != 1:
        raise ValueError(f"Stage {current} does not have exactly one non-failed transition")
    return candidates[0]
