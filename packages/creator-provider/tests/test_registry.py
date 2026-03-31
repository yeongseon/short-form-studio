import unittest

from creator_provider.registry import ModelCatalogEntry, ProviderCategory, ProviderRegistry


class ProviderRegistryTests(unittest.TestCase):
    def test_register_model_and_resolve_for_all_categories(self) -> None:
        registry = ProviderRegistry()
        entries = [
            ModelCatalogEntry(
                model_key="test-llm",
                provider_type="ollama",
                endpoint="http://ollama:11434",
                category=ProviderCategory.LLM,
            ),
            ModelCatalogEntry(
                model_key="test-image",
                provider_type="sd_local",
                endpoint="http://stable-diffusion:7860",
                category=ProviderCategory.IMAGE,
            ),
            ModelCatalogEntry(
                model_key="test-tts",
                provider_type="qwen_tts",
                endpoint="http://tts-qwen3:8100",
                category=ProviderCategory.TTS,
            ),
            ModelCatalogEntry(
                model_key="test-stt",
                provider_type="whisper",
                endpoint="http://stt-whisper:8200",
                category=ProviderCategory.STT,
            ),
        ]

        for entry in entries:
            with self.subTest(model_key=entry.model_key):
                registry.register_model(entry)
                resolved = registry.resolve(entry.model_key)
                self.assertEqual(resolved, entry)

    def test_resolve_raises_key_error_for_unknown_model(self) -> None:
        registry = ProviderRegistry()

        with self.assertRaises(KeyError):
            registry.resolve("unknown-model")

    def test_list_models_with_category_filter(self) -> None:
        registry = ProviderRegistry()
        llm_entry = ModelCatalogEntry(
            model_key="test-llm",
            provider_type="ollama",
            endpoint="http://ollama:11434",
            category=ProviderCategory.LLM,
        )
        image_entry = ModelCatalogEntry(
            model_key="test-image",
            provider_type="sd_local",
            endpoint="http://stable-diffusion:7860",
            category=ProviderCategory.IMAGE,
        )

        registry.register_model(llm_entry)
        registry.register_model(image_entry)

        llm_models = registry.list_models(category=ProviderCategory.LLM)

        self.assertEqual(llm_models, [llm_entry])

    def test_create_default_returns_registry_with_default_entries(self) -> None:
        registry = ProviderRegistry.create_default()

        self.assertEqual(len(registry.list_models()), 4)
        self.assertEqual(registry.resolve("qwen3-4b").category, ProviderCategory.LLM)
        self.assertEqual(registry.resolve("sd15").category, ProviderCategory.IMAGE)
        self.assertEqual(registry.resolve("qwen3-tts").category, ProviderCategory.TTS)
        self.assertEqual(registry.resolve("whisper-small").category, ProviderCategory.STT)

    def test_get_provider_raises_key_error_for_unregistered_provider_type(self) -> None:
        registry = ProviderRegistry()
        registry.register_model(
            ModelCatalogEntry(
                model_key="test-llm",
                provider_type="unregistered",
                endpoint="http://localhost:9999",
                category=ProviderCategory.LLM,
            )
        )

        with self.assertRaises(KeyError):
            registry.get_provider("test-llm")


if __name__ == "__main__":
    unittest.main()
