"""Unit tests for model health service."""

import pytest
from creator_service.model_health_service import (
    ModelHealthService,
    ModelHealthResult,
    ModelStatus,
)


@pytest.fixture
def health_service():
    """Create a model health service instance."""
    return ModelHealthService()


class TestModelHealthService:
    """Test suite for ModelHealthService."""

    def test_initialization_with_default_endpoints(self, health_service):
        """Test ModelHealthService initializes with default endpoints."""
        assert health_service.endpoints is not None
        assert "ollama" in health_service.endpoints
        assert "stable-diffusion" in health_service.endpoints
        assert "tts-qwen3" in health_service.endpoints
        assert "stt-whisper" in health_service.endpoints
        
        # Verify default URLs
        assert health_service.endpoints["ollama"] == "http://ollama:11434"
        assert health_service.endpoints["stable-diffusion"] == "http://stable-diffusion:7860"
        assert health_service.endpoints["tts-qwen3"] == "http://tts-qwen3:9880"
        assert health_service.endpoints["stt-whisper"] == "http://stt-whisper:9000"

    def test_initialization_with_env_variables(self, monkeypatch):
        """Test ModelHealthService initializes with environment variables."""
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://custom-ollama:11434")
        monkeypatch.setenv("STABLE_DIFFUSION_BASE_URL", "http://custom-sd:7860")
        
        service = ModelHealthService()
        
        assert service.endpoints["ollama"] == "http://custom-ollama:11434"
        assert service.endpoints["stable-diffusion"] == "http://custom-sd:7860"

    @pytest.mark.asyncio
    async def test_check_model_returns_result_with_correct_model_name(self, health_service):
        """Test check_model returns result with correct model_name."""
        result = await health_service.check_model("ollama")
        
        assert isinstance(result, ModelHealthResult)
        assert result.model_name == "ollama"
        assert result.endpoint == "http://ollama:11434"

    @pytest.mark.asyncio
    async def test_check_model_returns_unknown_for_invalid_model(self, health_service):
        """Test check_model returns UNKNOWN status for invalid model."""
        result = await health_service.check_model("invalid-model")
        
        assert result.status == ModelStatus.UNKNOWN
        assert result.error == "Unknown model"
        assert result.endpoint == "unknown"

    @pytest.mark.asyncio
    async def test_check_all_returns_results_for_all_models(self, health_service):
        """Test check_all returns results for all 4 models."""
        results = await health_service.check_all()
        
        assert isinstance(results, list)
        assert len(results) == 4
        
        model_names = {result.model_name for result in results}
        expected_models = {"ollama", "stable-diffusion", "tts-qwen3", "stt-whisper"}
        assert model_names == expected_models

    @pytest.mark.asyncio
    async def test_check_all_returns_model_health_results(self, health_service):
        """Test check_all returns ModelHealthResult instances."""
        results = await health_service.check_all()
        
        for result in results:
            assert isinstance(result, ModelHealthResult)
            assert result.model_name
            assert result.endpoint
            assert result.status in [ModelStatus.HEALTHY, ModelStatus.UNHEALTHY, ModelStatus.UNKNOWN]

    def test_health_paths_configured(self, health_service):
        """Test health paths are configured for all models."""
        assert health_service.health_paths is not None
        assert "ollama" in health_service.health_paths
        assert "stable-diffusion" in health_service.health_paths
        assert "tts-qwen3" in health_service.health_paths
        assert "stt-whisper" in health_service.health_paths
        
        # Verify health paths
        assert health_service.health_paths["ollama"] == "/api/tags"
        assert health_service.health_paths["stable-diffusion"] == "/sdapi/v1/options"

    def test_model_status_enum_values(self):
        """Test ModelStatus enum has expected values."""
        assert ModelStatus.HEALTHY.value == "healthy"
        assert ModelStatus.UNHEALTHY.value == "unhealthy"
        assert ModelStatus.UNKNOWN.value == "unknown"
