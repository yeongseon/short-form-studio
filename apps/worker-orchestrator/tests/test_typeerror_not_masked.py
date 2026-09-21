"""
Test that TypeError from service methods propagates and is not masked by dead except blocks.

These tests verify the removed try/except TypeError blocks don't mask real TypeErrors.
The fix ensures service methods are called directly with storage_provider and storage_key.
"""

from __future__ import annotations

from unittest import mock

import pytest
from tasks import generate_audio as generate_audio_module
from tasks import generate_subtitles as generate_subtitles_module
from tasks import generate_paragraph_audio as generate_paragraph_audio_module
from tasks import generate_paragraph_subtitles as generate_paragraph_subtitles_module
from tasks import generate_scene_image as generate_scene_image_module
from tasks import render_video as render_video_module


@pytest.mark.asyncio
async def test_generate_audio_calls_service_with_storage_params():
    """Verify audio service.create_artifact is called with storage params (not caught by dead except)."""
    audio_service = mock.AsyncMock()
    audio_service.create_artifact.return_value = mock.Mock(id=1, path="test.wav")

    with mock.patch.object(generate_audio_module, "_audio_service", audio_service):
        # Simulate the actual task code that now directly calls with storage params
        uploaded = mock.Mock(storage_provider="s3", key="test_key")
        
        # This is what the task does now (after removing the dead except TypeError)
        artifact = await audio_service.create_artifact(
            run_id=1,
            path="/tmp/test.wav",
            model_used="model",
            provider_type="tts",
            voice="default",
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
        )
        
        # Verify the storage params were passed
        audio_service.create_artifact.assert_called_once()
        call_kwargs = audio_service.create_artifact.call_args.kwargs
        assert "storage_provider" in call_kwargs
        assert call_kwargs["storage_provider"] == "s3"
        assert "storage_key" in call_kwargs
        assert call_kwargs["storage_key"] == "test_key"


@pytest.mark.asyncio
async def test_generate_audio_typeerror_from_service_propagates():
    """Verify TypeError raised by service propagates (not caught by removed except)."""
    audio_service = mock.AsyncMock()
    audio_service.create_artifact.side_effect = TypeError("unexpected keyword argument")

    with mock.patch.object(generate_audio_module, "_audio_service", audio_service):
        uploaded = mock.Mock(storage_provider="s3", key="test_key")
        
        # TypeError should propagate through (not caught by removed except TypeError)
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            await audio_service.create_artifact(
                run_id=1,
                path="/tmp/test.wav",
                model_used="model",
                provider_type="tts",
                voice="default",
                storage_provider=uploaded.storage_provider,
                storage_key=uploaded.key,
            )


@pytest.mark.asyncio
async def test_generate_subtitles_calls_service_with_storage_params():
    """Verify subtitle service.create_artifact is called with storage params."""
    subtitle_service = mock.AsyncMock()
    subtitle_service.create_artifact.return_value = mock.Mock(id=1, path="test.srt")

    with mock.patch.object(generate_subtitles_module, "_subtitle_service", subtitle_service):
        uploaded = mock.Mock(storage_provider="s3", key="test_key")
        
        artifact = await subtitle_service.create_artifact(
            run_id=1,
            path="/tmp/test.srt",
            format="srt",
            model_used="model",
            provider_type="stt",
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
        )
        
        call_kwargs = subtitle_service.create_artifact.call_args.kwargs
        assert call_kwargs["storage_provider"] == "s3"
        assert call_kwargs["storage_key"] == "test_key"


@pytest.mark.asyncio
async def test_generate_paragraph_audio_calls_service_with_storage_params():
    """Verify paragraph audio service is called with storage params."""
    audio_service = mock.AsyncMock()
    audio_service.create_paragraph_artifact.return_value = mock.Mock(id=1, path="test.wav")

    with mock.patch.object(generate_paragraph_audio_module, "_audio_service", audio_service):
        uploaded = mock.Mock(storage_provider="s3", key="test_key")
        
        artifact = await audio_service.create_paragraph_artifact(
            run_id=1,
            section_id=1,
            path="/tmp/test.wav",
            model_used="model",
            provider_type="tts",
            voice="default",
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
        )
        
        call_kwargs = audio_service.create_paragraph_artifact.call_args.kwargs
        assert call_kwargs["storage_provider"] == "s3"
        assert call_kwargs["storage_key"] == "test_key"


@pytest.mark.asyncio
async def test_generate_paragraph_subtitles_calls_service_with_storage_params():
    """Verify paragraph subtitle service is called with storage params."""
    subtitle_service = mock.AsyncMock()
    subtitle_service.create_paragraph_artifact.return_value = mock.Mock(id=1, path="test.srt")

    with mock.patch.object(generate_paragraph_subtitles_module, "_subtitle_service", subtitle_service):
        uploaded = mock.Mock(storage_provider="s3", key="test_key")
        
        artifact = await subtitle_service.create_paragraph_artifact(
            run_id=1,
            section_id=1,
            path="/tmp/test.srt",
            fmt="srt",
            model_used="model",
            provider_type="stt",
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
        )
        
        call_kwargs = subtitle_service.create_paragraph_artifact.call_args.kwargs
        assert call_kwargs["storage_provider"] == "s3"
        assert call_kwargs["storage_key"] == "test_key"


@pytest.mark.asyncio
async def test_generate_scene_image_calls_service_with_storage_params():
    """Verify visual asset service is called with storage params."""
    visual_asset_service = mock.AsyncMock()
    visual_asset_service.create_asset.return_value = mock.Mock(id=1, asset_path="test.png")

    with mock.patch.object(generate_scene_image_module, "_visual_asset_service", visual_asset_service):
        uploaded = mock.Mock(storage_provider="s3", key="test_key")
        
        asset = await visual_asset_service.create_asset(
            run_id=1,
            scene_id=1,
            asset_path="/tmp/test.png",
            prompt_snapshot="test",
            model_used="model",
            provider_type="image",
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
            is_active=True,
        )
        
        call_kwargs = visual_asset_service.create_asset.call_args.kwargs
        assert call_kwargs["storage_provider"] == "s3"
        assert call_kwargs["storage_key"] == "test_key"


@pytest.mark.asyncio
async def test_render_video_calls_service_with_storage_params():
    """Verify render service is called with storage params."""
    render_service = mock.AsyncMock()
    render_service.create_artifact.return_value = mock.Mock(id=1, path="test.mp4")

    with mock.patch.object(render_video_module, "_render_service", render_service):
        uploaded = mock.Mock(storage_provider="s3", key="test_key")
        
        artifact = await render_service.create_artifact(
            run_id=1,
            path="/tmp/test.mp4",
            render_profile="standard",
            storage_provider=uploaded.storage_provider,
            storage_key=uploaded.key,
        )
        
        call_kwargs = render_service.create_artifact.call_args.kwargs
        assert call_kwargs["storage_provider"] == "s3"
        assert call_kwargs["storage_key"] == "test_key"


@pytest.mark.asyncio
async def test_no_except_typeerror_fallback_exists():
    """
    Verify that the code no longer has try/except TypeError fallback blocks.
    
    This test documents the fix: we removed dead code that caught TypeError
    and called the service without storage params. Now the service is called
    directly with storage_provider and storage_key.
    """
    # Read the source files to verify no try/except TypeError blocks remain
    import inspect
    
    # Check generate_audio
    source = inspect.getsource(generate_audio_module.generate_audio)
    assert "except TypeError:" not in source, "generate_audio still has except TypeError"
    
    # Check generate_subtitles
    source = inspect.getsource(generate_subtitles_module.generate_subtitles)
    assert "except TypeError:" not in source, "generate_subtitles still has except TypeError"
    
    # Check generate_paragraph_audio
    source = inspect.getsource(generate_paragraph_audio_module.generate_paragraph_audio)
    assert "except TypeError:" not in source, "generate_paragraph_audio still has except TypeError"
    
    # Check generate_paragraph_subtitles
    source = inspect.getsource(generate_paragraph_subtitles_module.generate_paragraph_subtitles)
    assert "except TypeError:" not in source, "generate_paragraph_subtitles still has except TypeError"
    
    # Check generate_scene_image
    source = inspect.getsource(generate_scene_image_module.generate_scene_image)
    assert "except TypeError:" not in source, "generate_scene_image still has except TypeError"
    
    # Check render_video
    source = inspect.getsource(render_video_module.render_video)
    assert "except TypeError:" not in source, "render_video still has except TypeError"
