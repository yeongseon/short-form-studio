import re

from creator_domain.models import ScriptSection

_LEVEL_TWO_HEADING_RE = re.compile(r"^\s{0,3}##(?!#)\s*(.*?)\s*$")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _normalize_section_type(raw_heading: str) -> str:
    normalized = _NON_ALNUM_RE.sub("-", raw_heading.strip().lower()).strip("-")
    return normalized or "body"


def _join_and_trim(lines: list[str]) -> str:
    return "\n".join(lines).strip()


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


def parse_markdown(
    markdown: str, existing_sections: list[ScriptSection] | None = None
) -> list[ScriptSection]:
    if not markdown or not markdown.strip():
        return []

    extracted_sections = _extract_sections(markdown)
    existing_id_by_key: dict[tuple[str, int], str] = {}

    if existing_sections:
        for position, section in enumerate(existing_sections, start=1):
            key = (section.type, position)
            if key not in existing_id_by_key:
                existing_id_by_key[key] = section.section_id

    parsed_sections: list[ScriptSection] = []
    for position, (section_type, text) in enumerate(extracted_sections, start=1):
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
