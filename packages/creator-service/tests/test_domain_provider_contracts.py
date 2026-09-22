"""Provider compatibility paths expose the domain's neutral contracts."""

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.provider_catalog import ModelCatalogEntry, ProviderCategory
from creator_service.voice_preset import VoicePreset, resolve_voice_selection


def test_catalog_reexports_preserve_identity() -> None:
    from creator_domain.provider_catalog import ModelCatalogEntry, ProviderCategory
    from creator_provider import registry

    entry = registry.ModelCatalogEntry("voice", "local", "http://local", registry.ProviderCategory.TTS)

    assert type(entry) is ModelCatalogEntry
    assert entry.category is ProviderCategory.TTS
    assert entry.requires_gpu and entry.is_local
    assert entry.default_params is None


@pytest.mark.parametrize("name", [
    "ProviderError", "ProviderTimeoutError", "RateLimitError",
    "ProviderValidationError", "ProviderAuthError",
])
def test_provider_exception_reexports_preserve_catch_identity(name: str) -> None:
    from creator_domain import provider_errors
    from creator_provider import exceptions

    error_type = getattr(exceptions, name)
    error = error_type("failure")

    assert error_type is getattr(provider_errors, name)
    assert isinstance(error, provider_errors.ProviderError)
    assert str(error) == "failure"


@pytest.mark.parametrize("credential", ["", " \t\n"])
def test_voice_presence_check_rejects_blank_environment_credentials(monkeypatch: pytest.MonkeyPatch, credential: str) -> None:
    class Catalog:
        def resolve(self, model_key: str) -> ModelCatalogEntry:
            return ModelCatalogEntry(model_key, "openai_tts", "https://example.invalid", ProviderCategory.TTS, is_local=False)

    monkeypatch.setenv("OPENAI_API_KEY", credential)
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        resolve_voice_selection(VoicePreset("warm", "voice", "alloy"), registry=Catalog())
