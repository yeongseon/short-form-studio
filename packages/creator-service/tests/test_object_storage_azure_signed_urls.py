from __future__ import annotations

import importlib
import sys
import types


def _install_fake_azure(account_key: str | None = "secret") -> None:
    azure_mod = types.ModuleType("azure")
    storage_mod = types.ModuleType("azure.storage")
    blob_mod = types.ModuleType("azure.storage.blob")

    class _BlobSasPermissions:
        def __init__(self, read: bool = False) -> None:
            self.read = read

    class _BlobClient:
        def __init__(self, name: str) -> None:
            self.url = f"https://acct.blob.core.windows.net/artifacts/{name}"

    class _ContainerClient:
        def get_blob_client(self, name: str) -> _BlobClient:
            return _BlobClient(name)

    class _BlobServiceClient:
        def __init__(self) -> None:
            self.account_name = "acct"
            self.credential = types.SimpleNamespace(account_key=account_key)

        @classmethod
        def from_connection_string(cls, _conn: str) -> _BlobServiceClient:
            return cls()

        def get_container_client(self, _container: str) -> _ContainerClient:
            return _ContainerClient()

    class _ContentSettings:
        def __init__(self, content_type: str | None = None) -> None:
            self.content_type = content_type

    def _generate_blob_sas(**_kwargs: object) -> str:
        return "sig=fake"

    blob_mod.BlobServiceClient = _BlobServiceClient  # type: ignore[attr-defined]
    blob_mod.ContentSettings = _ContentSettings  # type: ignore[attr-defined]
    blob_mod.BlobSasPermissions = _BlobSasPermissions  # type: ignore[attr-defined]
    blob_mod.generate_blob_sas = _generate_blob_sas  # type: ignore[attr-defined]
    sys.modules["azure"] = azure_mod
    sys.modules["azure.storage"] = storage_mod
    sys.modules["azure.storage.blob"] = blob_mod


def test_azure_download_url_includes_sas_token(monkeypatch):
    _install_fake_azure(account_key="super-secret")
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "artifacts")
    monkeypatch.setenv("AZURE_STORAGE_PREFIX", "prefix")

    module = importlib.import_module("creator_service.object_storage")
    backend = module.AzureBlobStorageBackend()

    url = backend.download_url("42/render/output.mp4", expires_in=600)

    assert url.startswith(
        "https://acct.blob.core.windows.net/artifacts/prefix/42/render/output.mp4?"
    )
    assert "sig=fake" in url


def test_azure_download_url_raises_when_no_account_key(monkeypatch):
    _install_fake_azure(account_key=None)
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "artifacts")
    monkeypatch.delenv("AZURE_STORAGE_PREFIX", raising=False)
    monkeypatch.delenv("STORAGE_ALLOW_UNSIGNED_URLS", raising=False)

    module = importlib.import_module("creator_service.object_storage")
    backend = module.AzureBlobStorageBackend()
    import pytest

    with pytest.raises(module.StorageCredentialMissingError, match="credential missing"):
        backend.download_url("1/audio/audio.wav", expires_in=120)


def test_azure_download_url_unsigned_allowed_with_env_var(monkeypatch):
    _install_fake_azure(account_key=None)
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "artifacts")
    monkeypatch.delenv("AZURE_STORAGE_PREFIX", raising=False)
    monkeypatch.setenv("STORAGE_ALLOW_UNSIGNED_URLS", "true")

    module = importlib.import_module("creator_service.object_storage")
    backend = module.AzureBlobStorageBackend()

    url = backend.download_url("1/audio/audio.wav", expires_in=120)

    assert url == "https://acct.blob.core.windows.net/artifacts/1/audio/audio.wav?se=120"
