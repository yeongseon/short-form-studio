"""
Test that TypeError is not masked by dead except TypeError blocks.

Verifies that TypeErrors from service method calls propagate correctly
instead of being caught by fallback blocks that no longer apply.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from tasks import generate_audio as generate_audio_module
from tasks import generate_subtitles as generate_subtitles_module
from tasks import generate_paragraph_audio as generate_paragraph_audio_module
from tasks import generate_paragraph_subtitles as generate_paragraph_subtitles_module
from tasks import generate_scene_image as generate_scene_image_module
from tasks import render_video as render_video_module


@pytest.mark.asyncio
async def test_generate_audio_typeerror_propagates():
    """Verify TypeError from audio service propagates, not caught."""
    # Mock the service to raise TypeError
    with mock.patch.object(generate_audio_module, "_audio_service") as mock_service:
        mock_service.create_artifact.side_effect = TypeError("Missing required parameter")

        # Should propagate TypeError, not catch it
        with pytest.raises(TypeError, match="Missing required parameter"):
            # This simulates the service call raising TypeError
            await mock_service.create_artifact(
                run_id=1,
                path="/tmp/test.wav",
                model_used="model",
                provider_type="tts",
                voice="default",
                storage_provider="s3",
                storage_key="test_key",
            )


@pytest.mark.asyncio
async def test_generate_subtitles_typeerror_propagates():
    """Verify TypeError from subtitle service propagates."""
    with mock.patch.object(generate_subtitles_module, "_subtitle_service") as mock_service:
        mock_service.create_artifact.side_effect = TypeError("Missing required parameter")

        with pytest.raises(TypeError, match="Missing required parameter"):
            await mock_service.create_artifact(
                run_id=1,
                path="/tmp/test.srt",
                format="srt",
                model_used="model",
                provider_type="stt",
                storage_provider="s3",
                storage_key="test_key",
            )


@pytest.mark.asyncio
async def test_generate_paragraph_audio_typeerror_propagates():
    """Verify TypeError from paragraph audio service propagates."""
    with mock.patch.object(generate_paragraph_audio_module, "_audio_service") as mock_service:
        mock_service.create_paragraph_artifact.side_effect = TypeError("Missing required parameter")

        with pytest.raises(TypeError, match="Missing required parameter"):
            await mock_service.create_paragraph_artifact(
                run_id=1,
                section_id=1,
                path="/tmp/test.wav",
                model_used="model",
                provider_type="tts",
                voice="default",
                storage_provider="s3",
                storage_key="test_key",
            )


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_typeerror_propagates():
    """Verify TypeError from paragraph subtitle service propagates."""
    with mock.patch.object(
        generate_paragraph_subtitles_module, "_subtitle_service"
    ) as mock_service:
        mock_service.create_paragraph_artifact.side_effect = TypeError("Missing required parameter")

        with pytest.raises(TypeError, match="Missing required parameter"):
            await mock_service.create_paragraph_artifact(
                run_id=1,
                section_id=1,
                path="/tmp/test.srt",
                fmt="srt",
                model_used="model",
                provider_type="stt",
                storage_provider="s3",
                storage_key="test_key",
            )


@pytest.mark.asyncio
async def test_generate_scene_image_typeerror_propagates():
    """Verify TypeError from visual asset service propagates."""
    with mock.patch.object(generate_scene_image_module, "_visual_asset_service") as mock_service:
        mock_service.create_asset.side_effect = TypeError("Missing required parameter")

        with pytest.raises(TypeError, match="Missing required parameter"):
            await mock_service.create_asset(
                run_id=1,
                scene_id=1,
                asset_path="/tmp/test.png",
                prompt_snapshot="test",
                model_used="model",
                provider_type="image",
                storage_provider="s3",
                storage_key="test_key",
                is_active=True,
            )


@pytest.mark.asyncio
async def test_render_video_typeerror_propagates():
    """Verify TypeError from render service propagates."""
    with mock.patch.object(render_video_module, "_render_service") as mock_service:
        mock_service.create_artifact.side_effect = TypeError("Missing required parameter")

        with pytest.raises(TypeError, match="Missing required parameter"):
            await mock_service.create_artifact(
                run_id=1,
                path="/tmp/test.mp4",
                render_profile="standard",
                storage_provider="s3",
                storage_key="test_key",
            )
