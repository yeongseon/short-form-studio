from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import JsonValue

TaskName = Literal[
    "generate_script", "generate_visual_plan", "generate_audio", "generate_subtitles",
    "render_video", "generate_scene_image", "generate_paragraph_audio", "generate_paragraph_subtitles",
]


@dataclass(frozen=True, slots=True)
class TaskSubmission:
    task_name: TaskName
    run_id: int
    args: tuple[JsonValue, ...] = ()
    kwargs: Mapping[str, JsonValue] = field(default_factory=dict)
    task_id: str | None = None


class TaskDispatcher(Protocol):
    def uses_queue(self) -> bool: ...
    def dispatch(self, submission: TaskSubmission) -> str: ...
    def cancel(self, task_id: str) -> None: ...


class SynchronousTaskExecutionError(Exception):
    pass
