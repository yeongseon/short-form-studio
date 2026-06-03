"""Viral YouTube Shorts script generation prompts.

Based on data analysis of 756,851+ short-form videos:
- Revid.ai 2026 Data Report (756K videos)
- TheContentLabs linguistic teardown (3,633 transcripts, 165 mega-virals)
- Paddy Galloway 3.3B Shorts study
- Virvid.ai hook structure research (2025-2026)

Key findings encoded:
- Question-based hooks = most effective (12.2%)
- Mega-viral sentences avg 14 words (not fragments)
- 1.84 questions per video in 1M+ tier
- Clean language travels further (6.7% profanity vs 12.2% in long-tail)
- First 3 seconds determine algorithmic distribution
- 20-60 second optimal duration depending on content type
"""

from __future__ import annotations

from typing import Any, Literal, get_args


# --- Language configuration (single source of truth) ---

SupportedLanguage = Literal["ko", "en", "ja", "zh", "es", "pt", "fr", "de"]
SUPPORTED_LANGUAGES: tuple[str, ...] = get_args(SupportedLanguage)

LANGUAGE_INSTRUCTIONS: dict[SupportedLanguage, str] = {
    "ko": "한국어로 스크립트를 작성하세요.",
    "en": "Write the script in English.",
    "ja": "日本語でスクリプトを作成してください。",
    "zh": "用中文写脚本。",
    "es": "Escribe el guión en español.",
    "pt": "Escreva o roteiro em português.",
    "fr": "Écrivez le script en français.",
    "de": "Schreiben Sie das Skript auf Deutsch.",
}


# --- Niche presets ---

NICHE_PRESETS: dict[str, dict[str, Any]] = {
    "facts": {
        "name": "놀라운 사실",
        "name_en": "Amazing Facts",
        "description": "Did-you-know style factual content",
        "target_duration_seconds": 30,
        "target_word_count": (80, 100),
        "hook_style": "question",
        "tone": "fascinating, authoritative",
        "example_hooks": [
            "당신의 뇌는 매일 이것을 하고 있습니다",
            "지구상에서 가장 위험한 물질은 의외로...",
            "과학자들이 최근 발견한 충격적인 사실",
        ],
        "visual_style": "cinematic, dramatic lighting, close-up details",
    },
    "horror": {
        "name": "공포/미스터리",
        "name_en": "Horror & Mystery",
        "description": "Scary stories, unsolved mysteries, creepy facts",
        "target_duration_seconds": 45,
        "target_word_count": (120, 150),
        "hook_style": "micro_story",
        "tone": "eerie, suspenseful, whispered urgency",
        "example_hooks": [
            "이 영상을 본 사람들은 밤에 잠을 못 잤습니다",
            "절대 검색하면 안 되는 단어가 있습니다",
            "이 사진에서 이상한 점을 찾으셨나요?",
        ],
        "visual_style": "dark, moody, desaturated, shadows, found-footage aesthetic",
    },
    "motivation": {
        "name": "동기부여",
        "name_en": "Motivation",
        "description": "Self-improvement, mindset, success stories",
        "target_duration_seconds": 40,
        "target_word_count": (100, 130),
        "hook_style": "bold_claim",
        "tone": "confident, direct, powerful",
        "example_hooks": [
            "성공한 사람들은 절대 하지 않는 습관 하나",
            "당신이 매일 낭비하는 시간의 정체",
            "부자들이 아침 5시에 일어나는 진짜 이유",
        ],
        "visual_style": "high contrast, silhouettes, golden hour, powerful typography",
    },
    "psychology": {
        "name": "심리학",
        "name_en": "Psychology & Human Behavior",
        "description": "Human behavior, cognitive biases, social experiments",
        "target_duration_seconds": 35,
        "target_word_count": (90, 120),
        "hook_style": "curiosity_gap",
        "tone": "intriguing, analytical, mind-blowing",
        "example_hooks": [
            "당신이 모르는 사이에 뇌가 당신을 속이는 방법",
            "왜 우리는 싫어하는 사람에게 끌릴까?",
            "이 심리 실험의 결과를 아무도 예상하지 못했습니다",
        ],
        "visual_style": "abstract, neural patterns, split-screen comparisons, clean minimal",
    },
    "science": {
        "name": "과학",
        "name_en": "Science Explained",
        "description": "Scientific concepts made fascinating",
        "target_duration_seconds": 35,
        "target_word_count": (90, 120),
        "hook_style": "question",
        "tone": "curious, awe-inspiring, accessible",
        "example_hooks": [
            "우주에서 가장 차가운 곳은 지구에 있습니다",
            "물 한 잔에 들어있는 원자의 수를 알면 놀랍습니다",
            "빛보다 빠른 것이 실제로 존재합니다",
        ],
        "visual_style": "space imagery, microscopic views, infographic overlays, vibrant colors",
    },
    "food": {
        "name": "음식",
        "name_en": "Food & Cooking",
        "description": "Food facts, recipes, food science",
        "target_duration_seconds": 25,
        "target_word_count": (60, 80),
        "hook_style": "visual_shock",
        "tone": "energetic, appetizing, surprising",
        "example_hooks": [
            "이 음식의 원래 색깔을 보면 절대 못 먹습니다",
            "전 세계에서 가장 비싼 음식 한 입 가격",
            "당신이 매일 먹는 이것의 진실",
        ],
        "visual_style": "macro food photography, vibrant saturated colors, steam/sizzle effects",
    },
    "tech": {
        "name": "기술/가젯",
        "name_en": "Tech & Gadgets",
        "description": "Tech facts, gadget reveals, future tech",
        "target_duration_seconds": 20,
        "target_word_count": (50, 70),
        "hook_style": "bold_claim",
        "tone": "excited, futuristic, authoritative",
        "example_hooks": [
            "이 기술이 5년 안에 당신의 직업을 없앱니다",
            "세계에서 가장 작은 컴퓨터의 크기는...",
            "99%의 사람이 모르는 스마트폰 숨겨진 기능",
        ],
        "visual_style": "sleek product shots, neon accents, futuristic UI, clean backgrounds",
    },
}

# --- Hook templates by style ---

HOOK_TEMPLATES: dict[str, str] = {
    "question": "질문형 훅: 시청자가 이미 궁금해하는 진짜 질문으로 시작. 수사적 질문이 아니라 머리에서 답을 구하고 싶어지는 질문.",
    "bold_claim": "강력 주장형 훅: 기존 상식에 도전하는 한 문장. 반직관적이거나 놀라운 사실 제시.",
    "curiosity_gap": "호기심 갭 훅: 정보 가려움을 만드는 문장. 뭔가를 알려줄 것 같지만 아직 안 알려줌.",
    "micro_story": "마이크로 스토리 훅: 1-2문장의 이야기 시작. '나는 X했다. 그런데...' 형태로 내러티브 추진력 생성.",
    "visual_shock": "시각 충격 훅: 화면에 충격적 숫자나 이미지를 먼저 보여주고 설명 시작.",
}


# --- System prompt builder ---



def build_viral_system_prompt(
    niche: str | None = None,
    language: SupportedLanguage = "ko",
) -> str:
    """Build a system prompt that instructs the LLM to write viral short-form scripts.

    Args:
        niche: One of NICHE_PRESETS keys, or None for general.
        language: Target language code.
    """
    # Validate language against single source of truth
    if language not in LANGUAGE_INSTRUCTIONS:
        import logging
        logging.getLogger(__name__).warning(
            "Unsupported language %r, falling back to 'ko'", language
        )
        language = "ko"

    preset = NICHE_PRESETS.get(niche or "", None)

    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, f"Write the script in {language}.")
    # Core viral formula (data-backed)
    base = f"""You are an expert YouTube Shorts scriptwriter who consistently produces videos with 1M+ views.

{lang_instruction}

## VIRAL SCRIPT RULES (data from 756,851 video analysis):

1. **HOOK (첫 3초, 12단어 이하)**: 스크롤을 멈추는 한 문장. 첫 단어가 0.5초 안에 시작.
   - "Hey"로 시작하면 중앙값 조회수 19배 상승
   - 질문형 훅이 가장 효과적 (12.2%)
   - 절대 "이 영상에서는..."으로 시작하지 마세요
   - "Stop"으로 시작하지 마세요 (중앙값 3,147뷰)

2. **CURIOSITY (4-10초)**: 오픈루프 생성. 시청자가 "계속 봐야 해"라고 느끼게.
   - 약속 하나만. 두 개 아닌 하나.
   - 현재시제 + 능동태 사용

3. **VALUE (11-40초)**: 빠른 팩트 3-5개 전달.
   - 문장당 평균 14단어 (짧은 파편이 아닌 완전한 문장)
   - 영상당 질문 1.84개 삽입 (답을 주며 호기심 루프 유지)
   - 욕설 금지 (바이럴 영상은 6.7%만 욕설 포함)

4. **PAYOFF (마지막 5-10초)**: 훅에서 한 약속 이행. 결론.

5. **CTA (마지막 2-3초)**: 짧은 행동 유도.

## OUTPUT FORMAT:
마크다운으로 출력. 각 섹션을 ## 헤딩으로 구분:

## Hook
(1-2문장, 스크롤 멈추는 충격적 오프닝)

## Body
(핵심 내용 3-5단락, 각 단락은 하나의 장면)

## Conclusion
(약속 이행 + CTA)

중요: display_text(화면 자막)을 각 단락 아래에 > 인용 형태로 포함하세요.
예시:
## Hook
놀라운 사실 하나 알려드릴게요.
> 🤯 놀라운 사실"""

    # Add niche-specific instructions
    if preset:
        target_words = preset["target_word_count"]
        hook_style = preset["hook_style"]
        hook_desc = HOOK_TEMPLATES.get(hook_style, "")

        base += f"""

## NICHE: {preset["name"]} ({preset["name_en"]})

- 목표 길이: {preset["target_duration_seconds"]}초 ({target_words[0]}-{target_words[1]}단어)
- 톤: {preset["tone"]}
- 훅 스타일: {hook_desc}
- 참고 훅 예시:
  - "{preset["example_hooks"][0]}"
  - "{preset["example_hooks"][1]}"
  - "{preset["example_hooks"][2]}"
"""
    else:
        base += """

## DEFAULT:
- 목표 길이: 30-45초 (80-120단어)
- 톤: fascinating, authoritative
- 훅 스타일: 질문형 또는 강력 주장형
"""

    return base


def build_viral_visual_prompt(niche: str | None = None) -> str:
    """Build enhanced visual plan system prompt with viral visual patterns."""
    preset = NICHE_PRESETS.get(niche or "", None)
    visual_style = preset["visual_style"] if preset else "cinematic, dramatic, high contrast"

    return f"""You are a visual director for viral YouTube Shorts (9:16 vertical, 1080x1920).

## VISUAL RULES FOR VIRAL SHORTS:

1. **첫 프레임이 가장 강력해야 함** — 첫 장면이 전체 영상에서 가장 시각적으로 충격적이어야 합니다.
2. **빠른 시각 전환** — 3-5초마다 새로운 시각적 요소. 단조로움 금지.
3. **텍스트 오버레이 필수** — 화면에 핵심 단어/숫자 항상 표시 (60%가 무음 시청).
4. **클로즈업 선호** — 와이드샷보다 클로즈업이 모바일에서 임팩트 강함.
5. **대비와 색감** — 고대비, 채도 높은 색상으로 피드에서 눈에 띄게.

## STYLE: {visual_style}

For each scene, produce:
- A detailed image-generation prompt (describe the visual, not the narration)
- Style tags (array)
- Mood
- Composition notes (prefer: close-up, extreme close-up, Dutch angle, low angle)
- on_screen_text: key text/number to overlay on the image

Return a JSON array of objects with keys:
section_id, prompt, style_tags (array), mood, composition, on_screen_text.
Only return the JSON array, no markdown fencing or extra text."""
