from collections.abc import Mapping
from typing import Protocol

from creator_domain.exceptions import ServiceUnavailableError
from creator_domain.task_dispatch import TaskDispatcher, TaskSubmission
from pydantic import JsonValue


class DispatchRun(Protocol):
    @property
    def project_id(self) -> int: ...

    @property
    def status(self) -> str: ...


class DispatchStorage(Protocol):
    async def conditional_update_run(
        self, run_id: int, updates: dict[str, JsonValue], *,
        expected_stages: frozenset[str], workspace_id: int | None = None,
        rejected_statuses: frozenset[str] | None = None,
    ) -> tuple[bool, Mapping[str, JsonValue] | None]: ...


class DispatchRunService(Protocol):
    @property
    def storage(self) -> DispatchStorage: ...

    async def get_run(self, run_id: int, *, workspace_id: int | None = None) -> DispatchRun | None: ...


class UnconfiguredDispatcher:
    def uses_queue(self) -> bool:
        return False

    def dispatch(self, submission: TaskSubmission) -> str:
        raise ServiceUnavailableError("Task dispatcher is not configured")

    def cancel(self, task_id: str) -> None:
        raise ServiceUnavailableError("Task dispatcher is not configured")


class DispatchRuntime:
    def __init__(self, dispatcher: TaskDispatcher | None = None) -> None:
        self.dispatcher = dispatcher if dispatcher is not None else UnconfiguredDispatcher()

    def configure(self, dispatcher: TaskDispatcher) -> None:
        self.dispatcher = dispatcher

    def _use_celery_dispatch(self) -> bool:
        return self.dispatcher.uses_queue()
