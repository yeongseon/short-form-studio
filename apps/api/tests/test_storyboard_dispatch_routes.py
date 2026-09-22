from creator_domain.task_dispatch import TaskSubmission
from creator_service.task_dispatch_service import task_dispatch_service
import pytest

from .test_creator_storyboard import (
    StubAudioArtifact, StubScriptDraft, StubSection, _make_run,
    _patch_quota_functions, stub_storyboard_services as stub_storyboard_services,
)
from .test_storyboard_pending_dispatch import boundary as boundary


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "task_type", "bulk"), [
    ("paragraphs/sec-1/generate-audio", "generate_paragraph_audio", False),
    ("paragraphs/sec-1/generate-subtitles", "generate_paragraph_subtitles", False),
    ("generate-all-audio", "generate_paragraph_audio", True),
    ("generate-all-subtitles", "generate_paragraph_subtitles", True),
])
async def test_routes_forward_pending_id_through_real_wrappers(
    client, stub_storyboard_services, boundary, monkeypatch: pytest.MonkeyPatch,
    path: str, task_type: str, bulk: bool,
) -> None:
    run_service, script_service, audio_service = stub_storyboard_services
    tracking, cancellation, _ = boundary
    run_service.runs[4] = _make_run(4)
    script_service.drafts[4] = StubScriptDraft(structured_script=[
        StubSection(section_id="sec-1", text="one"), StubSection(section_id="sec-2", text="two"),
    ])
    audio_service.by_section[(4, "sec-1")] = StubAudioArtifact(id=1, section_id="sec-1", path="one.wav")
    audio_service.by_run[4] = [
        StubAudioArtifact(id=1, section_id="sec-1", path="one.wav"),
        StubAudioArtifact(id=2, section_id="sec-2", path="two.wav"),
    ] if task_type == "generate_paragraph_subtitles" else []
    _patch_quota_functions(monkeypatch, {
        "generate_paragraph_audio_endpoint", "generate_paragraph_subtitles_endpoint",
        "generate_all_paragraph_audio", "generate_all_paragraph_subtitles",
    })
    submissions: list[TaskSubmission] = []

    def publish(submission: TaskSubmission) -> str:
        assert submission.task_id is not None
        assert tracking.events[-1] == ("pending", submission.task_id)
        submissions.append(submission)
        return submission.task_id

    monkeypatch.setattr(task_dispatch_service.dispatcher, "dispatch", publish)

    response = await client.post(f"/api/creator/runs/4/storyboard/{path}", json={})

    assert response.status_code == 202, response.text
    tasks = await tracking.list_run_tasks(4)
    ids = [submission.task_id for submission in submissions]
    assert len(ids) == (2 if bulk else 1)
    assert len(set(ids)) == len(ids)
    assert {task.celery_task_id for task in tasks} == set(ids)
    assert all(task.status == "queued" for task in tasks)
    assert [submission.kwargs["section_id"] for submission in submissions] == (["sec-1", "sec-2"] if bulk else ["sec-1"])
    assert all(submission.task_name == task_type and submission.args == (4,) for submission in submissions)
    payload = response.json()
    assert ([item["task_id"] for item in payload["tasks"]] if bulk else [payload["task_id"]]) == ids
    assert cancellation.calls == []
