"""Parse JSON scene array into ScriptSection domain objects."""

from __future__ import annotations

import json

from creator_domain.models.script_draft import ScriptSection


def parse_json_scenes(raw_json: str) -> list[ScriptSection]:
    """Parse a JSON string containing scene definitions.

    Expected format::

        {
          "scenes": [
            {
              "type": "hook",
              "text": "script text here",
              "image_prompt": "detailed visual description...",
              "speaker": "host",
              "mood": "exciting",
              "composition": "medium shot",
              "style_tags": ["cinematic", "sci-fi"],
              "duration": 5.0,
              "display_text": "optional subtitle text"
            }
          ]
        }

    Also accepts a bare array of scene objects (no wrapper).
    """
    data = json.loads(raw_json)

    # Accept both {"scenes": [...]} and bare [...]
    if isinstance(data, dict):
        scenes_data = data.get("scenes", [])
    elif isinstance(data, list):
        scenes_data = data
    else:
        raise ValueError("JSON must be an object with 'scenes' array or a bare array of scenes")

    if not scenes_data:
        raise ValueError("No scenes found in JSON")
    if len(scenes_data) > 200:
        raise ValueError("Too many scenes (max 200)")

    sections: list[ScriptSection] = []
    for idx, scene in enumerate(scenes_data):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene at index {idx} must be an object")

        text = scene.get("text", "").strip()
        if not text:
            raise ValueError(f"Scene at index {idx} is missing required 'text' field")
        if len(text) > 10000:
            raise ValueError(f"Scene at index {idx} text exceeds 10000 character limit")

        section_type = scene.get("type", "body")
        section_id = f"{section_type}-{idx + 1}"

        image_prompt_val = scene.get("image_prompt")
        if image_prompt_val and len(image_prompt_val) > 2000:
            raise ValueError(
                f"Scene {idx + 1} image_prompt exceeds 2000 character limit"
            )


        sections.append(
            ScriptSection(
                section_id=section_id,
                type=section_type,
                text=text,
                display_text=scene.get("display_text"),
                speaker=scene.get("speaker", "host"),
                duration=scene.get("duration"),
                turn_kind=scene.get("turn_kind"),
                visual_override=None,
                image_prompt=image_prompt_val,
                mood=scene.get("mood"),
                composition=scene.get("composition"),
                style_tags=scene.get("style_tags", []),
            )
        )

    return sections
