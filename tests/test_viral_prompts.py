"""Unit tests for viral_prompts module."""

import sys
from pathlib import Path

# Add worker tasks to path
sys.path.insert(0, str(Path(__file__).parent.parent / "apps" / "worker-orchestrator"))

from tasks.viral_prompts import NICHE_PRESETS, SUPPORTED_LANGUAGES, build_viral_system_prompt


class TestBuildViralSystemPrompt:
    def test_known_niche_returns_prompt(self):
        result = build_viral_system_prompt("facts", "ko")
        assert isinstance(result, str)
        assert len(result) > 100

    def test_all_presets_produce_output(self):
        for niche in NICHE_PRESETS:
            result = build_viral_system_prompt(niche, "en")
            assert isinstance(result, str)
            assert len(result) > 50

    def test_unknown_niche_returns_generic(self):
        result = build_viral_system_prompt("nonexistent_niche", "ko")
        assert isinstance(result, str)
        assert len(result) > 50

    def test_none_niche_returns_generic(self):
        result = build_viral_system_prompt(None, "ko")
        assert isinstance(result, str)
        assert len(result) > 50

    def test_language_appears_in_prompt(self):
        result = build_viral_system_prompt("facts", "en")
        assert "English" in result

    def test_different_niches_produce_different_prompts(self):
        facts = build_viral_system_prompt("facts", "ko")
        horror = build_viral_system_prompt("horror", "ko")
        assert facts != horror

    def test_invalid_language_defaults_to_ko(self):
        result = build_viral_system_prompt("facts", "xx_invalid")
        assert "한국어" in result

    def test_supported_languages_constant(self):
        assert "ko" in SUPPORTED_LANGUAGES
        assert "en" in SUPPORTED_LANGUAGES
        assert len(SUPPORTED_LANGUAGES) >= 8

    def test_all_supported_languages_produce_output(self):
        for lang in SUPPORTED_LANGUAGES:
            result = build_viral_system_prompt("facts", lang)
            assert isinstance(result, str)
            assert len(result) > 100
