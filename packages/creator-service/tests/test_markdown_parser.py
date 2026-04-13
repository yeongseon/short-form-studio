from creator_service.markdown_parser import parse_markdown


def test_parse_standard_markdown_headings():
    markdown = """## hook
Grab attention now.

## intro
Welcome to the episode.

## body
Main explanation.

## outro
Thanks for watching.
"""

    sections = parse_markdown(markdown)

    assert [section.type for section in sections] == ["hook", "intro", "body", "outro"]
    assert [section.section_id for section in sections] == ["hook-1", "intro-2", "body-3", "outro-4"]
    assert [section.text for section in sections] == [
        "Grab attention now.",
        "Welcome to the episode.",
        "Main explanation.",
        "Thanks for watching.",
    ]
    for section in sections:
        assert section.display_text == section.text
        assert section.speaker == "host"
        assert section.duration is None
        assert section.turn_kind is None
        assert section.visual_override is None


def test_parse_markdown_with_duplicate_heading_types():
    markdown = """## hook
Opening A.

## hook
Opening B.

## body
Main section.
"""

    sections = parse_markdown(markdown)

    assert [section.type for section in sections] == ["hook", "hook", "body"]
    assert [section.section_id for section in sections] == ["hook-1", "hook-2", "body-3"]


def test_parse_markdown_without_headings_creates_single_body_section():
    markdown = "First line.\n\nSecond line."

    sections = parse_markdown(markdown)

    assert len(sections) == 1
    assert sections[0].type == "body"
    assert sections[0].section_id == "body-1"
    assert sections[0].text == "First line.\n\nSecond line."


def test_parse_empty_markdown_returns_empty_list():
    assert parse_markdown("") == []
    assert parse_markdown("   \n\n  ") == []


def test_stable_id_preservation_reuses_existing_ids_for_same_type_and_position():
    markdown = """## hook
Original hook.

## intro
Original intro.

## body
Original body.
"""
    existing = parse_markdown(markdown)
    existing[0].section_id = "sec-custom-hook"
    existing[1].section_id = "sec-custom-intro"

    updated_markdown = """## hook
Updated hook text.

## intro
Updated intro text.

## body
Updated body text.
"""
    reparsed = parse_markdown(updated_markdown, existing_sections=existing)

    assert [section.section_id for section in reparsed] == [
        "sec-custom-hook",
        "sec-custom-intro",
        "body-3",
    ]


def test_stable_id_changes_when_sections_reordered():
    original_markdown = """## hook
Hook text.

## intro
Intro text.

## body
Body text.
"""
    existing = parse_markdown(original_markdown)

    reordered_markdown = """## intro
Intro text.

## hook
Hook text.

## body
Body text.
"""
    reparsed = parse_markdown(reordered_markdown, existing_sections=existing)

    assert [section.section_id for section in reparsed] == ["intro-1", "hook-2", "body-3"]
    assert reparsed[0].section_id != existing[1].section_id
    assert reparsed[1].section_id != existing[0].section_id


def test_malformed_markdown_best_effort_parsing_handles_partial_headings_and_empty_sections():
    markdown = """##hook
Hook line.
### not-a-level-two-heading

##

##intro
"""

    sections = parse_markdown(markdown)

    assert [section.type for section in sections] == ["hook", "body", "intro"]
    assert [section.section_id for section in sections] == ["hook-1", "body-2", "intro-3"]
    assert sections[0].text == "Hook line.\n### not-a-level-two-heading"
    assert sections[1].text == ""
    assert sections[2].text == ""


def test_section_ids_are_deterministic_for_same_input():
    markdown = """## cta
Like and subscribe.

## body
One more thing.
"""

    first = parse_markdown(markdown)
    second = parse_markdown(markdown)

    assert [section.section_id for section in first] == [section.section_id for section in second]


def test_parse_korean_headings():
    markdown = """## 도입
여러분, 안녕하세요.

## 본문
오늘 주제를 소개합니다.

## 마무리
감사합니다.
"""

    sections = parse_markdown(markdown)

    assert [section.type for section in sections] == ["도입", "본문", "마무리"]
    assert [section.section_id for section in sections] == ["도입-1", "본문-2", "마무리-3"]
    assert sections[0].text == "여러분, 안녕하세요."
