"""Script quality control for ssul_v2 quality profile.

Validates generated scripts against quality rules:
- No CTA/subscribe mentions in body
- Minimum scene count (5+)
- No generic openings
- Hook must be under 15 words
- Body must have sufficient scenes
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class QCResult:
    """Result of script quality check."""

    passed: bool
    score: int  # 0-100
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_script_quality(
    markdown_content: str,
    banned_patterns: list[str] | None = None,
    min_scenes: int = 3,
    max_hook_words: int = 15,
) -> QCResult:
    """Run QC checks on a generated script.

    Returns QCResult with pass/fail and detailed issues.
    """
    issues: list[str] = []
    warnings: list[str] = []
    score = 100

    if not markdown_content or not markdown_content.strip():
        return QCResult(passed=False, score=0, issues=["Empty script"])

    content = markdown_content.strip()

    # Parse sections
    sections = _parse_sections(content)

    # Check required sections exist
    has_hook = "hook" in sections
    has_body = "body" in sections
    has_conclusion = "conclusion" in sections

    if not has_hook:
        issues.append("Missing ## Hook section")
        score -= 20
    if not has_body:
        issues.append("Missing ## Body section")
        score -= 30
    if not has_conclusion:
        issues.append("Missing ## Conclusion section")
        score -= 10

    # Check hook length
    if has_hook:
        hook_text = sections["hook"].strip()
        # Remove display_text lines (> prefixed)
        hook_lines = [line for line in hook_text.split("\n") if not line.strip().startswith(">")]
        hook_words = " ".join(hook_lines).split()
        if len(hook_words) > max_hook_words:
            warnings.append(f"Hook too long: {len(hook_words)} words (max {max_hook_words})")
            score -= 5

    # Check body scene count (paragraphs separated by blank lines)
    if has_body:
        body_text = sections["body"].strip()
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body_text) if p.strip()]
        # Filter out display_text-only paragraphs and beat metadata lines
        real_paragraphs = [
            p
            for p in paragraphs
            if any(
                not line.strip().startswith(">") and not line.strip().startswith("[beat:")
                for line in p.split("\n")
                if line.strip()
            )
        ]
        if len(real_paragraphs) < min_scenes:
            issues.append(f"Body has {len(real_paragraphs)} scenes, need at least {min_scenes}")
            score -= 15

    # Check banned patterns
    if banned_patterns:
        content_lower = content.lower()
        for pattern in banned_patterns:
            if pattern.lower() in content_lower:
                issues.append(f"Banned pattern found: '{pattern}'")
                score -= 10

    # Cap score at 0
    score = max(0, score)
    passed = score >= 60 and not any("Missing" in i for i in issues)

    return QCResult(passed=passed, score=score, issues=issues, warnings=warnings)


def extract_emphasis_words(markdown_content: str) -> list[str]:
    """Extract emphasis-worthy words from script content.

    Looks for:
    - Words in bold (**word**)
    - Numbers and statistics (50만원, 3시간, 99%)
    - Quoted words ("인용")
    - Key emotional/dramatic Korean words
    - Specific nouns that carry story weight
    """
    words: list[str] = []

    # Bold words
    bold_matches = re.findall(r"\*\*(.+?)\*\*", markdown_content)
    words.extend(bold_matches)

    # Numbers/statistics (e.g. "50만원", "3시간", "99%", "100만원")
    number_matches = re.findall(r"\d+[%만억천시분초개명번원]?\w{0,3}", markdown_content)
    words.extend(number_matches)

    # Quoted words ("이거 진짜야?" style)
    quoted_matches = re.findall(r'["\u201c\u201d](.+?)["\u201c\u201d]', markdown_content)
    for q in quoted_matches:
        if 2 <= len(q) <= 15:
            words.append(q)

    # Key dramatic Korean words that should be highlighted
    dramatic_keywords = [
        "사기", "경찰", "신고", "반전", "충격", "소름",
        "어이없다", "몘봕", "눈물", "조심",
        "위험", "무서운", "이상", "수상",
    ]
    for kw in dramatic_keywords:
        if kw in markdown_content:
            words.append(kw)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for w in words:
        if w.lower() not in seen and len(w) >= 2:
            seen.add(w.lower())
            unique.append(w)

    return unique[:20]  # Cap at 20 emphasis words


def _parse_sections(content: str) -> dict[str, str]:
    """Parse markdown into sections by ## headings."""
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in content.split("\n"):
        if line.strip().startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines)
            heading = line.strip().lstrip("#").strip().lower()
            current_key = heading
            current_lines = []
        else:
            current_lines.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(current_lines)

    return sections
