"""SF-27: simple Track domain — Visual/Text/Caption/Narration/Music roles with
ordered content. Text and captions carry text directly (no fake image assets);
media roles carry asset references. Track/content compatibility is validated.
Advanced compositing and many stacked video layers are out of scope.
"""

from __future__ import annotations

import pytest
from creator_domain.models import Track, TrackContent, TrackRole
from pydantic import ValidationError


def _media(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "start_seconds": 0.0,
        "duration_seconds": 4.0,
        "asset_id": 1,
    }
    payload.update(overrides)
    return payload


def _text(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "start_seconds": 0.0,
        "duration_seconds": 4.0,
        "text": "hello",
    }
    payload.update(overrides)
    return payload


def _track(role: TrackRole, content: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"id": "track-1", "role": role, "content": content}
    payload.update(overrides)
    return payload


def test_track_roles_defined() -> None:
    assert {r.value for r in TrackRole} == {
        "visual",
        "text",
        "caption",
        "narration",
        "music",
    }


def test_visual_track_accepts_media_content() -> None:
    track = Track.model_validate(_track(TrackRole.VISUAL, [_media()]))
    assert track.role is TrackRole.VISUAL
    assert isinstance(track.content[0], TrackContent)
    assert track.content[0].asset_id == 1
    assert track.content[0].text is None


def test_text_track_accepts_text_without_asset() -> None:
    track = Track.model_validate(_track(TrackRole.TEXT, [_text()]))
    assert track.content[0].text == "hello"
    assert track.content[0].asset_id is None


def test_caption_track_accepts_text_without_asset() -> None:
    track = Track.model_validate(_track(TrackRole.CAPTION, [_text(text="a caption")]))
    assert track.content[0].text == "a caption"


@pytest.mark.parametrize("role", [TrackRole.NARRATION, TrackRole.MUSIC])
def test_audio_tracks_accept_media_content(role: TrackRole) -> None:
    track = Track.model_validate(_track(role, [_media()]))
    assert track.content[0].asset_id == 1


def test_text_role_rejects_media_content() -> None:
    with pytest.raises(ValidationError):
        Track.model_validate(_track(TrackRole.TEXT, [_media()]))


def test_visual_role_rejects_text_content() -> None:
    with pytest.raises(ValidationError):
        Track.model_validate(_track(TrackRole.VISUAL, [_text()]))


def test_caption_role_rejects_media_content() -> None:
    with pytest.raises(ValidationError):
        Track.model_validate(_track(TrackRole.CAPTION, [_media()]))


def test_content_requires_exactly_one_of_asset_or_text() -> None:
    with pytest.raises(ValidationError):
        TrackContent.model_validate({"start_seconds": 0.0, "duration_seconds": 1.0})
    with pytest.raises(ValidationError):
        TrackContent.model_validate(
            {"start_seconds": 0.0, "duration_seconds": 1.0, "asset_id": 1, "text": "x"}
        )


def test_track_content_ordered_by_start() -> None:
    track = Track.model_validate(
        _track(
            TrackRole.TEXT,
            [
                _text(text="second", start_seconds=5.0, duration_seconds=2.0),
                _text(text="first", start_seconds=0.0, duration_seconds=3.0),
            ],
        )
    )
    assert [c.text for c in track.ordered_content()] == ["first", "second"]


def test_track_rejects_overlapping_content() -> None:
    with pytest.raises(ValidationError):
        Track.model_validate(
            _track(
                TrackRole.NARRATION,
                [
                    _media(start_seconds=0.0, duration_seconds=5.0),
                    _media(start_seconds=3.0, duration_seconds=2.0),
                ],
            )
        )


def test_track_allows_empty_content() -> None:
    track = Track.model_validate(_track(TrackRole.MUSIC, []))
    assert track.content == []


def test_track_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Track.model_validate(_track(TrackRole.TEXT, [_text()], unexpected="x"))


def test_track_deterministic_serialization() -> None:
    payload = _track(TrackRole.CAPTION, [_text(text="a"), _text(text="b", start_seconds=4.0)])
    first = Track.model_validate(payload).to_json()
    second = Track.model_validate(payload).to_json()
    assert first == second
    assert Track.from_dict(payload).to_json() == first
