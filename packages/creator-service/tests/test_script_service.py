import asyncio

import pytest
from creator_domain.models.script_draft import ScriptSection
from creator_service.markdown_parser import parse_markdown
from creator_service.script_service import InMemoryScriptStorage, ScriptService


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def storage() -> InMemoryScriptStorage:
    return InMemoryScriptStorage()


@pytest.fixture
def service(storage: InMemoryScriptStorage) -> ScriptService:
    return ScriptService(storage)


def test_save_draft_creates_version_1(service: ScriptService) -> None:
    draft = run(
        service.save_draft(
            run_id=101,
            source_type="pasted_markdown",
            markdown_content="## hook\nHello",
        )
    )

    assert draft.run_id == 101
    assert draft.version == 1


def test_save_draft_increments_version(service: ScriptService) -> None:
    run(service.save_draft(run_id=102, source_type="pasted_markdown", markdown_content="## hook\nFirst"))
    second = run(
        service.save_draft(
            run_id=102,
            source_type="edited_manually",
            markdown_content="## hook\nSecond",
        )
    )

    assert second.version == 2


def test_save_draft_parses_markdown_when_no_structured_script(service: ScriptService) -> None:
    markdown = "## hook\nHook line\n\n## body\nBody line"

    draft = run(service.save_draft(run_id=103, source_type="pasted_markdown", markdown_content=markdown))

    assert draft.structured_script is not None
    assert draft.structured_script == parse_markdown(markdown)


def test_save_draft_preserves_explicit_structured_script(service: ScriptService) -> None:
    explicit = [
        ScriptSection(
            section_id="custom-1",
            type="custom",
            text="Explicit text",
            display_text="Explicit display",
            speaker="host",
            duration=None,
            turn_kind=None,
            visual_override=None,
        )
    ]

    draft = run(
        service.save_draft(
            run_id=104,
            source_type="edited_manually",
            markdown_content="## hook\nIgnored by explicit sections",
            structured_script=explicit,
        )
    )

    assert draft.structured_script is not None
    assert [section.section_id for section in draft.structured_script] == ["custom-1"]
    assert [section.type for section in draft.structured_script] == ["custom"]
    assert [section.text for section in draft.structured_script] == ["Explicit text"]


def test_save_draft_stable_section_ids(service: ScriptService) -> None:
    first_markdown = "## hook\nFirst hook\n\n## intro\nFirst intro"
    second_markdown = "## hook\nUpdated hook\n\n## intro\nUpdated intro"

    first = run(service.save_draft(run_id=105, source_type="pasted_markdown", markdown_content=first_markdown))
    second = run(service.save_draft(run_id=105, source_type="edited_manually", markdown_content=second_markdown))

    assert first.structured_script is not None
    assert second.structured_script is not None
    assert [section.section_id for section in second.structured_script] == [
        section.section_id for section in first.structured_script
    ]


def test_get_active_draft_returns_latest(service: ScriptService) -> None:
    run(service.save_draft(run_id=106, source_type="pasted_markdown", markdown_content="## hook\nV1"))
    run(service.save_draft(run_id=106, source_type="edited_manually", markdown_content="## hook\nV2"))

    active = run(service.get_active_draft(106))

    assert active is not None
    assert active.version == 2
    assert active.markdown_content == "## hook\nV2"


def test_get_active_draft_returns_none_for_missing(service: ScriptService) -> None:
    assert run(service.get_active_draft(9999)) is None


def test_list_draft_versions_returns_newest_first(service: ScriptService) -> None:
    run(service.save_draft(run_id=107, source_type="pasted_markdown", markdown_content="## hook\nV1"))
    run(service.save_draft(run_id=107, source_type="edited_manually", markdown_content="## hook\nV2"))
    run(service.save_draft(run_id=107, source_type="edited_manually", markdown_content="## hook\nV3"))

    drafts = run(service.list_draft_versions(107))

    assert [draft.version for draft in drafts] == [3, 2, 1]


@pytest.mark.asyncio
async def test_concurrent_saves_produce_unique_versions() -> None:
    """Two concurrent saves for the same run_id must produce distinct versions."""
    storage = InMemoryScriptStorage()
    service = ScriptService(storage)

    results = await asyncio.gather(
        service.save_draft(run_id=200, source_type="pasted_markdown", markdown_content="## hook\nA"),
        service.save_draft(run_id=200, source_type="pasted_markdown", markdown_content="## hook\nB"),
    )

    versions = sorted(d.version for d in results)
    assert versions == [1, 2], f"Expected unique versions [1, 2], got {versions}"


@pytest.mark.asyncio
async def test_concurrent_saves_across_service_instances() -> None:
    """Two ScriptService instances sharing one storage must still produce unique versions."""
    storage = InMemoryScriptStorage()
    service_a = ScriptService(storage)
    service_b = ScriptService(storage)

    results = await asyncio.gather(
        service_a.save_draft(run_id=201, source_type="pasted_markdown", markdown_content="## hook\nA"),
        service_b.save_draft(run_id=201, source_type="pasted_markdown", markdown_content="## hook\nB"),
    )

    versions = sorted(d.version for d in results)
    assert versions == [1, 2], f"Expected unique versions [1, 2], got {versions}"
