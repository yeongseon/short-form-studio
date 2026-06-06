import re

from creator_domain.models import ScriptSection

_LEVEL_TWO_HEADING_RE = re.compile(r"^\s{0,3}##(?!#)\s*(.*?)\s*$")
_NON_ALNUM_RE = re.compile(r"[^\w]+", re.UNICODE)

# Minimum paragraph length to be considered a scene (avoids splitting on stray newlines)
_MIN_PARAGRAPH_CHARS = 20


def _normalize_section_type(raw_heading: str) -> str:
    normalized = _NON_ALNUM_RE.sub("-", raw_heading.strip().lower()).strip("-")
    return normalized or "body"


def _join_and_trim(lines: list[str]) -> str:
    return "\n".join(lines).strip()


def _split_body_paragraphs(text: str) -> list[str]:
    """Split a body section into individual paragraphs (scenes).

    Each paragraph is separated by one or more blank lines.
    A paragraph consists of narrative text optionally followed by a > quote line.
    Only paragraphs with at least _MIN_PARAGRAPH_CHARS of content are kept.
    """
    # Split on double newline (blank line separator)
    raw_paragraphs = re.split(r"\n\s*\n", text.strip())

    paragraphs: list[str] = []
    for para in raw_paragraphs:
        stripped = para.strip()
        if len(stripped) >= _MIN_PARAGRAPH_CHARS:
            paragraphs.append(stripped)

    return paragraphs if len(paragraphs) > 1 else [text.strip()]


def _extract_sections(markdown: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    extracted: list[tuple[str, str]] = []
    pending_lines: list[str] = []
    current_type: str | None = None

    for line in lines:
        heading_match = _LEVEL_TWO_HEADING_RE.match(line)
        if heading_match:
            if current_type is None:
                prelude = _join_and_trim(pending_lines)
                if prelude:
                    extracted.append(("body", prelude))
            else:
                extracted.append((current_type, _join_and_trim(pending_lines)))

            current_type = _normalize_section_type(heading_match.group(1))
            pending_lines = []
            continue

        pending_lines.append(line)

    if current_type is None:
        body_text = _join_and_trim(pending_lines)
        return [("body", body_text)] if body_text else []

    extracted.append((current_type, _join_and_trim(pending_lines)))
    return extracted


def _expand_body_sections(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Expand body sections with multiple paragraphs into individual scenes.

    Hook and Conclusion sections are kept as-is.
    Body sections are split by paragraph boundaries so each paragraph
    becomes its own scene (important for generating per-scene images).
    """
    expanded: list[tuple[str, str]] = []

    for section_type, text in sections:
        if section_type == "body":
            paragraphs = _split_body_paragraphs(text)
            for para in paragraphs:
                expanded.append(("body", para))
        else:
            expanded.append((section_type, text))

    return expanded


def parse_markdown(
    markdown: str, existing_sections: list[ScriptSection] | None = None
) -> list[ScriptSection]:
    if not markdown or not markdown.strip():
        return []

    extracted_sections = _extract_sections(markdown)
    # Split body sections into individual scenes (1 paragraph = 1 scene)
    expanded_sections = _expand_body_sections(extracted_sections)

    existing_id_by_key: dict[tuple[str, int], str] = {}

    if existing_sections:
        for position, section in enumerate(existing_sections, start=1):
            key = (section.type, position)
            if key not in existing_id_by_key:
                existing_id_by_key[key] = section.section_id

    parsed_sections: list[ScriptSection] = []
    for position, (section_type, text) in enumerate(expanded_sections, start=1):
        key = (section_type, position)
        section_id = existing_id_by_key.get(key, f"{section_type}-{position}")
        parsed_sections.append(
            ScriptSection(
                section_id=section_id,
                type=section_type,
                text=text,
                display_text=text,
                speaker="host",
                duration=None,
                turn_kind=None,
                visual_override=None,
            )
        )

    return parsed_sections
