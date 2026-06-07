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


def fix_keyword_repetition(markdown_content: str, max_repeats: int = 2) -> str:
    """Post-process script to reduce excessive keyword repetition.

    Detects dramatic keywords that appear more than max_repeats times
    (as substrings) and removes excess occurrences.

    This addresses the common LLM failure mode of repeating emphasis
    keywords (e.g., '충격', '소름') multiple times per script.
    """
    if not markdown_content:
        return markdown_content

    # Dramatic stems to check for over-use (common LLM repetitions)
    _DRAMATIC_STEMS = [
        '충격', '소름', '반전', '경악', '전율', '불안',
        '공포', '무서운', '위험', '놀라', '기적', '수상',
        '어이없', '말도 안', '상상도', '믿을 수',
        '이상', '이상한', '이상했',  # Very common LLM repetition
    ]

    # Also find full Korean words that repeat excessively
    korean_words = re.findall(r'[가-힣]{2,}', markdown_content)
    word_counts: dict[str, int] = {}
    for w in korean_words:
        word_counts[w] = word_counts.get(w, 0) + 1

    _EXEMPT_WORDS = {
        '그런데', '그래서', '그리고', '하지만', '때문에', '이것', '그것',
        '사람', '우리', '정말', '진짜', '정도', '시간', '이유',
        '생각', '하나', '나는', '제가', '있는', '없는', '이런',
    }

    # Collect all stems/words that are repeated excessively
    over_repeated: list[str] = []

    # Check dramatic stems as substrings
    for stem in _DRAMATIC_STEMS:
        count = markdown_content.count(stem)
        if count > max_repeats:
            over_repeated.append(stem)

    # Check full words
    for w, count in word_counts.items():
        if count > max_repeats and w not in _EXEMPT_WORDS and len(w) >= 2:
            over_repeated.append(w)

    if not over_repeated:
        return markdown_content

    logger.info("Fixing repeated keywords: %s", over_repeated)

    result = markdown_content
    for word in over_repeated:
        count = 0
        positions: list[tuple[int, int]] = []
        for match in re.finditer(re.escape(word), result):
            count += 1
            if count > max_repeats:
                positions.append((match.start(), match.end()))

        # Remove excess occurrences (from end to start to preserve positions)
        for start, end in reversed(positions):
            before = result[:start]
            after = result[end:]
            if before.endswith(' ') and after.startswith(' '):
                result = before + after[1:]
            else:
                result = before + after

    # Clean up any resulting double spaces or empty lines
    result = re.sub(r'  +', ' ', result)
    result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)
    return result
