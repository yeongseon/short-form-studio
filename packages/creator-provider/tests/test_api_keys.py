"""Tests for API key resolution utility."""
from __future__ import annotations

import os
from unittest import mock

import pytest

from creator_provider.api_keys import list_configured_providers, resolve_api_key


class TestResolveApiKey:
    def test_resolve_existing_key(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}):
            assert resolve_api_key("openai") == "sk-test123"

    def test_resolve_key_strips_whitespace(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "  sk-test123  "}):
            assert resolve_api_key("openai") == "sk-test123"

    def test_resolve_missing_key_required(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="not configured"):
                _ = resolve_api_key("openai")

    def test_resolve_empty_key_required(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with pytest.raises(ValueError, match="not configured"):
                _ = resolve_api_key("openai")

    def test_resolve_missing_key_not_required(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert resolve_api_key("openai", required=False) is None

    def test_resolve_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown provider"):
            _ = resolve_api_key("unknown_provider")

    def test_resolve_case_insensitive(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "ak-test"}):
            assert resolve_api_key("Anthropic") == "ak-test"

    def test_all_providers_resolvable(self):
        env = {
            "OPENAI_API_KEY": "ok1",
            "ANTHROPIC_API_KEY": "ak1",
            "GOOGLE_API_KEY": "gk1",
            "STABILITY_API_KEY": "sk1",
            "ELEVENLABS_API_KEY": "ek1",
        }
        with mock.patch.dict(os.environ, env):
            for provider in ["openai", "anthropic", "google", "stability", "elevenlabs"]:
                assert resolve_api_key(provider) is not None


class TestListConfiguredProviders:
    def test_no_providers_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            assert list_configured_providers() == []

    def test_some_providers_configured(self):
        with mock.patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-test", "ELEVENLABS_API_KEY": "ek-test"},
            clear=True,
        ):
            result = list_configured_providers()
            assert "openai" in result
            assert "elevenlabs" in result
            assert "anthropic" not in result
