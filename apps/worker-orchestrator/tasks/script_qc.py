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

    # Check hook length and quality
    if has_hook:
        hook_text = sections["hook"].strip()
        # Remove display_text lines (> prefixed)
        hook_lines = [line for line in hook_text.split("\n") if not line.strip().startswith(">")]
        hook_body = " ".join(hook_lines).strip()
        hook_words = hook_body.split()
        if len(hook_words) > max_hook_words:
            warnings.append(f"Hook too long: {len(hook_words)} words (max {max_hook_words})")
            score -= 5
        # Check hook starts with result, not time word
        _TIME_STARTERS = ["어제", "오늘", "몇일 전", "얼마 전", "작년", "지난", "어느 날"]
        for ts in _TIME_STARTERS:
            if hook_body.startswith(ts):
                warnings.append(f"Hook starts with time word '{ts}' — should be result-first")
                score -= 3
                break

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

    # Check conclusion quality (should end with specific detail, not generic moral)
    if has_conclusion:
        conclusion_text = sections["conclusion"].strip()
        # Remove display_text lines
        conclusion_lines = [line for line in conclusion_text.split("\n") if not line.strip().startswith(">")]
        conclusion_body = " ".join(conclusion_lines).strip()
        _WEAK_CONCLUSIONS = [
            "기억에 남", "조심하세요", "주의하세요", "조심해야", "주의해야",
            "다시는 이런", "앞으로는", "교훈을 얻",
        ]
        for weak in _WEAK_CONCLUSIONS:
            if weak in conclusion_body:
                warnings.append(f"Weak conclusion (generic): contains '{weak}'")
                score -= 3
                break
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


def strengthen_weak_conclusion(markdown_content: str) -> str:
    """Detect and fix weak conclusions that end with generic morals instead of specific details.

    If the conclusion contains weak patterns (generic morals, memory statements),
    replace it with the last concrete detail from Body3 (the climax) reframed as
    a "later I found out" sting.

    This addresses Oracle feedback that conclusions should end with a specific
    detail or aftermath, not a generic emotional wrap-up.
    """
    if not markdown_content:
        return markdown_content

    # Parse sections
    sections = _parse_sections(markdown_content)
    conclusion_key = None
    for k in sections:
        if "conclusion" in k:
            conclusion_key = k
            break

    if not conclusion_key:
        return markdown_content

    conclusion_text = sections[conclusion_key].strip()
    # Get narration lines only (skip display_text)
    conclusion_lines = [line for line in conclusion_text.split("\n") if line.strip() and not line.strip().startswith(">")]
    conclusion_body = " ".join(conclusion_lines).strip()

    # Detect weak conclusion patterns
    _WEAK_PATTERNS = [
        "기억에 남", "조심하세요", "주의하세요", "조심해야", "주의해야",
        "다시는 이런", "앞으로는", "교훈을 얻", "배웠습니다",
        "여러분도 조심", "조심합시다", "기억납니다",
    ]

    is_weak = any(wp in conclusion_body for wp in _WEAK_PATTERNS)
    if not is_weak:
        return markdown_content

    # Try to extract a concrete detail from Body3 for the sting
    body3_key = None
    for k in sections:
        if "body3" in k or ("body" in k and "3" in k):
            body3_key = k
            break

    if not body3_key:
        # Can't find Body3, use a generic but stronger ending
        new_conclusion = "그 뒤로 저는 중고거래를 한 번도 다시 하지 않았습니다."
    else:
        body3_text = sections[body3_key].strip()
        body3_lines = [line for line in body3_text.split("\n") if line.strip() and not line.strip().startswith(">") and not line.strip().startswith("[")]

        # Look for key nouns in Body3 to build a sting
        # Common patterns: 경찰, 사기, 범죄, 절도, etc.
        body3_full = " ".join(body3_lines)
        if "경찰" in body3_full:
            new_conclusion = "나중에 알고보니 그 사람은 전과 3범이었다고 합니다."
        elif "사기" in body3_full:
            new_conclusion = "나중에 같은 수법으로 피해자가 5명 더 있었다는 사실을 알게 됐습니다."
        elif "도망" in body3_full or "도둑" in body3_full:
            new_conclusion = "그 사람은 아직도 잡히지 않았다고 합니다."
        elif "오해" in body3_full:
            new_conclusion = "그 후로 저는 중고거래 할 때 항상 신분증부터 확인합니다."
        else:
            new_conclusion = "그 뒤로 저는 중고거래를 다시는 하지 않았습니다."

    # Rebuild the conclusion section
    # Preserve display_text if present
    display_lines = [line for line in conclusion_text.split("\n") if line.strip().startswith(">")]
    new_section = new_conclusion
    if display_lines:
        new_section += "\n" + "\n".join(display_lines)

    # Replace conclusion in markdown
    result = markdown_content
    # Find and replace the conclusion section content
    conclusion_heading = f"## {conclusion_key.title() if conclusion_key == 'conclusion' else conclusion_key}"
    # Use regex to find ## Conclusion ... (until end or next ##)
    pattern = r'(## [Cc]onclusion[^\n]*)\n(.*?)(?=\n## |\Z)'
    match = re.search(pattern, result, re.DOTALL)
    if match:
        heading = match.group(1)
        result = result[:match.start()] + heading + "\n" + new_section + result[match.end():]
        logger.info("Strengthened weak conclusion: '%s' -> '%s'", conclusion_body[:50], new_conclusion[:50])

    return result


# --- Korean Grammar Post-Processing (#553) ---

# Common LLM Korean grammar errors: pattern -> replacement
_GRAMMAR_FIXES: list[tuple[str, str]] = [
    # Broken verb + auxiliary combinations
    (r'느낌이\s*했', '느낌이 들었'),  # 느낌이 했습니다 → 느낌이 들었습니다
    (r'생각이\s*했', '생각이 들었'),  # 생각이 했습니다 → 생각이 들었습니다
    (r'기분이\s*했', '기분이 들었'),  # 기분이 했다 → 기분이 들었다
    (r'예감이\s*했', '예감이 들었'),  # 예감이 했다 → 예감이 들었다
    # Double particles (incorrect particle stacking)
    (r'을를', '를'),
    (r'이가', '가'),
    (r'은는', '는'),
    (r'에서에', '에서'),
    # Broken sentence endings
    (r'(\S)ㄴ\s했', r'\1했'),  # Random ㄴ before 했
    (r'있습니다있', '있습니다'),  # Repeated ending
    (r'됩니다됩', '됩니다'),  # Repeated ending
    # Broken verb conjugation (Oracle-flagged: '사기 치려는 었고')
    (r'려는\s*었', '려는 것이었'),  # X하려는 었고 → X하려는 것이었고
    (r'려는\s*었고', '려는 것이었고'),  # explicit variant
    (r'하는\s*었', '하는 것이었'),  # X하는 었 → X하는 것이었
    (r'(\S)ㄴ\s했', r'\1했'),  # Random ㄴ before 했
    (r'있습니다있', '있습니다'),  # Repeated ending
    (r'됩니다됩', '됩니다'),  # Repeated ending
    # Common spacing errors
    (r'할수있', '할 수 있'),
    (r'할수없', '할 수 없'),
    (r'것같', '것 같'),
    (r'줄알', '줄 알'),
    # Overly formal closings that break flow in 썰쇼츠
    (r'감사합니다\.?\s*$', ''),  # Remove 감사합니다 at script end
]


def fix_korean_grammar(text: str) -> str:
    """Apply pattern-based Korean grammar fixes to LLM-generated text.

    Catches common broken patterns that Korean LLMs produce:
    - Incorrect verb+auxiliary (느낌이 했 → 느낌이 들었)
    - Double particles (을를 → 를)
    - Broken sentence endings
    - Missing spaces in compound constructions

    Returns:
        Corrected text. If no patterns match, returns input unchanged.
    """
    if not text:
        return text

    result = text
    corrections = 0
    for pattern, replacement in _GRAMMAR_FIXES:
        new_result = re.sub(pattern, replacement, result)
        if new_result != result:
            corrections += 1
            result = new_result

    if corrections:
        logger.info("Korean grammar: applied %d corrections", corrections)

    # Clean up trailing whitespace and double spaces
    result = re.sub(r'  +', ' ', result)
    result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)
    return result.strip()


# CJK character ranges that should NOT appear in Korean scripts
# Chinese (CJK Unified Ideographs): U+4E00-U+9FFF
# We keep Korean Hangul (U+AC00-U+D7AF), Hangul Jamo, and common symbols
_CJK_STRIP_PATTERN = re.compile(
    r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+'
)


def strip_non_korean_cjk(text: str) -> str:
    """Remove stray Chinese/CJK characters from Korean script text.

    Llama-4-Scout and similar models sometimes output Chinese characters
    (e.g. 最后, 重要) mixed into Korean text. This strips them while
    preserving Korean Hangul, numbers, punctuation, and Latin characters.

    Returns:
        Cleaned text with CJK ideographs removed.
    """
    if not text:
        return text

    result = _CJK_STRIP_PATTERN.sub('', text)
    # Clean up double spaces left by removal
    result = re.sub(r'  +', ' ', result)
    # Clean up empty lines left by removal
    result = re.sub(r'\n\s*\n\s*\n', '\n\n', result)

    removed_count = len(_CJK_STRIP_PATTERN.findall(text))
    if removed_count:
        logger.info("CJK cleanup: removed %d Chinese character sequences", removed_count)

    return result.strip()
