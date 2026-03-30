"""Smoke tests for Celery tasks."""

import pytest
from tasks import generate_script, generate_visual_plan, generate_scene_image, generate_audio, generate_subtitles, render_video


class TestTaskRegistration:
    """Test that all tasks are registered and callable."""

    def test_generate_script_callable(self):
        """Test that generate_script task is callable."""
        result = generate_script("test-run-123")
        assert result == {"status": "placeholder", "run_id": "test-run-123"}

    def test_generate_visual_plan_callable(self):
        """Test that generate_visual_plan task is callable."""
        result = generate_visual_plan("test-run-123")
        assert result == {"status": "placeholder", "run_id": "test-run-123"}

    def test_generate_scene_image_callable(self):
        """Test that generate_scene_image task is callable."""
        result = generate_scene_image("test-run-123", "scene-001")
        assert result == {"status": "placeholder", "run_id": "test-run-123", "scene_id": "scene-001"}

    def test_generate_audio_callable(self):
        """Test that generate_audio task is callable."""
        result = generate_audio("test-run-123")
        assert result == {"status": "placeholder", "run_id": "test-run-123"}

    def test_generate_subtitles_callable(self):
        """Test that generate_subtitles task is callable."""
        result = generate_subtitles("test-run-123")
        assert result == {"status": "placeholder", "run_id": "test-run-123"}

    def test_render_video_callable(self):
        """Test that render_video task is callable."""
        result = render_video("test-run-123")
        assert result == {"status": "placeholder", "run_id": "test-run-123"}


class TestTaskImportability:
    """Test that all task modules can be imported."""

    def test_all_tasks_importable(self):
        """Test that all task modules are importable."""
        from tasks import generate_audio
        from tasks import generate_scene_image
        from tasks import generate_script
        from tasks import generate_subtitles
        from tasks import generate_visual_plan
        from tasks import render_video
        
        assert generate_audio
        assert generate_scene_image
        assert generate_script
        assert generate_subtitles
        assert generate_visual_plan
        assert render_video
