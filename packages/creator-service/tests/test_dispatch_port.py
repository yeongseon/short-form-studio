from creator_domain.exceptions import ServiceUnavailableError
from creator_domain.task_dispatch import TaskSubmission
from creator_service.task_dispatch_service import TaskDispatchService
import pytest


class RecordingDispatcher:
    def __init__(self, queued: bool = False) -> None:
        self.queued = queued
        self.submissions: list[TaskSubmission] = []
        self.cancelled: list[str] = []

    def uses_queue(self) -> bool:
        return self.queued

    def dispatch(self, submission: TaskSubmission) -> str:
        self.submissions.append(submission)
        return submission.task_id or "injected-task"

    def cancel(self, task_id: str) -> None:
        self.cancelled.append(task_id)


def test_injected_dispatcher_receives_exact_submission() -> None:
    port = RecordingDispatcher()
    service = TaskDispatchService(port)

    result = service.dispatch_generate_script(9, "idea", "model", None, task_id="chosen-id")

    assert result == "chosen-id"
    assert port.submissions == [TaskSubmission(
        "generate_script", 9, kwargs={"run_id": 9, "idea_brief": "idea", "model_key": "model",
                                     "instructions": None, "niche": None, "language": "ko"},
        task_id="chosen-id",
    )]


def test_unconfigured_dispatch_fails_closed() -> None:
    service = TaskDispatchService()

    with pytest.raises(ServiceUnavailableError):
        service.dispatch_render_video(9, "vertical")
