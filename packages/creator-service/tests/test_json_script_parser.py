"""Tests for json_script_parser module."""
import json

import pytest

from creator_service.json_script_parser import parse_json_scenes


class TestParseJsonScenes:
    """Tests for parse_json_scenes function."""

    def test_valid_json_with_scenes_wrapper(self):
        raw = json.dumps({
            "scenes": [
                {"type": "hook", "text": "Hello world"},
                {"type": "body", "text": "Some content"},
            ]
        })
        sections = parse_json_scenes(raw)
        assert len(sections) == 2
        assert sections[0].section_id == "hook-1"
        assert sections[0].type == "hook"
        assert sections[0].text == "Hello world"
        assert sections[1].section_id == "body-2"
        assert sections[1].type == "body"
        assert sections[1].text == "Some content"

    def test_valid_json_bare_array(self):
        raw = json.dumps([
            {"type": "hook", "text": "Hello"},
            {"type": "cta", "text": "Subscribe"},
        ])
        sections = parse_json_scenes(raw)
        assert len(sections) == 2
        assert sections[0].type == "hook"
        assert sections[1].type == "cta"

    def test_preserves_image_prompt(self):
        raw = json.dumps({
            "scenes": [
                {
                    "type": "hook",
                    "text": "Hello",
                    "image_prompt": "A futuristic city at night",
                }
            ]
        })
        sections = parse_json_scenes(raw)
        assert sections[0].image_prompt == "A futuristic city at night"

    def test_preserves_mood_composition_style_tags(self):
        raw = json.dumps({
            "scenes": [
                {
                    "type": "body",
                    "text": "Content",
                    "mood": "exciting",
                    "composition": "wide shot",
                    "style_tags": ["cinematic", "dark"],
                }
            ]
        })
        sections = parse_json_scenes(raw)
        assert sections[0].mood == "exciting"
        assert sections[0].composition == "wide shot"
        assert sections[0].style_tags == ["cinematic", "dark"]

    def test_preserves_all_fields(self):
        raw = json.dumps({
            "scenes": [
                {
                    "type": "hook",
                    "text": "Script text",
                    "display_text": "Display text",
                    "speaker": "narrator",
                    "duration": 5.5,
                    "turn_kind": "monologue",
                    "image_prompt": "A beautiful sunset",
                    "mood": "peaceful",
                    "composition": "close-up",
                    "style_tags": ["warm", "golden"],
                }
            ]
        })
        sections = parse_json_scenes(raw)
        s = sections[0]
        assert s.text == "Script text"
        assert s.display_text == "Display text"
        assert s.speaker == "narrator"
        assert s.duration == 5.5
        assert s.turn_kind == "monologue"
        assert s.image_prompt == "A beautiful sunset"
        assert s.mood == "peaceful"
        assert s.composition == "close-up"
        assert s.style_tags == ["warm", "golden"]

    def test_default_values(self):
        raw = json.dumps({"scenes": [{"text": "Just text"}]})
        sections = parse_json_scenes(raw)
        s = sections[0]
        assert s.type == "body"
        assert s.speaker == "host"
        assert s.image_prompt is None
        assert s.mood is None
        assert s.composition is None
        assert s.style_tags == []
        assert s.duration is None
        assert s.display_text is None

    def test_empty_scenes_raises(self):
        raw = json.dumps({"scenes": []})
        with pytest.raises(ValueError, match="No scenes found"):
            parse_json_scenes(raw)

    def test_empty_string_raises(self):
        with pytest.raises(json.JSONDecodeError):
            parse_json_scenes("")

    def test_missing_text_raises(self):
        raw = json.dumps({"scenes": [{"type": "hook"}]})
        with pytest.raises(ValueError, match="missing required 'text' field"):
            parse_json_scenes(raw)

    def test_whitespace_only_text_raises(self):
        raw = json.dumps({"scenes": [{"type": "hook", "text": "   "}]})
        with pytest.raises(ValueError, match="missing required 'text' field"):
            parse_json_scenes(raw)

    def test_non_dict_scene_raises(self):
        raw = json.dumps({"scenes": ["not a dict"]})
        with pytest.raises(ValueError, match="must be an object"):
            parse_json_scenes(raw)

    def test_non_array_non_dict_raises(self):
        with pytest.raises(ValueError, match="JSON must be"):
            parse_json_scenes('"just a string"')

    def test_section_ids_are_type_indexed(self):
        raw = json.dumps({
            "scenes": [
                {"type": "hook", "text": "A"},
                {"type": "body", "text": "B"},
                {"type": "body", "text": "C"},
                {"type": "cta", "text": "D"},
            ]
        })
        sections = parse_json_scenes(raw)
        assert sections[0].section_id == "hook-1"
        assert sections[1].section_id == "body-2"
        assert sections[2].section_id == "body-3"
        assert sections[3].section_id == "cta-4"

    def test_title_in_wrapper_is_ignored(self):
        raw = json.dumps({
            "title": "My Project",
            "scenes": [{"type": "hook", "text": "Hello"}],
        })
        sections = parse_json_scenes(raw)
        assert len(sections) == 1
        assert sections[0].text == "Hello"
