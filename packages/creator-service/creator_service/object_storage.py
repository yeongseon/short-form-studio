"""Object storage abstraction for artifact files.

Selects backend based on STORAGE_BACKEND env var:
- 'local' (default): LocalStorageBackend using ARTIFACT_ROOT
- 's3': S3StorageBackend (requires boto3)
- 'azure_blob': AzureBlobStorageBackend (requires azure-storage-blob)
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


@dataclass
class StorageResult:
    """Result of an upload operation."""

    key: str
    size_bytes: int
    content_type: str
    checksum: str  # MD5 hex digest
    storage_provider: str  # 'local', 's3', 'azure_blob'


class ArtifactStorageBackend(Protocol):
    """Interface for artifact file storage."""

    def upload(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        """Upload artifact data and return storage metadata."""
        ...

    def download_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a URL for downloading the artifact.

        For local: returns a file:// path or relative path.
        For cloud: returns a presigned/SAS URL.
        """
        ...

    def download_bytes(self, key: str) -> bytes:
        """Download artifact data as bytes."""
        ...

    def delete(self, key: str) -> bool:
        """Delete artifact. Returns True if deleted, False if not found."""
        ...

    def exists(self, key: str) -> bool:
        """Check if artifact exists."""
        ...


class LocalStorageBackend:
    """Local filesystem storage. Default for development."""

    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root or os.getenv("ARTIFACT_ROOT", "data/artifacts"))

    def _safe_key(self, key: str) -> str:
        """Validate key to prevent path traversal attacks."""
        resolved = (self._root / key).resolve()
        root_resolved = self._root.resolve()
        if not resolved.is_relative_to(root_resolved):
            raise ValueError(f"Invalid key (path traversal): {key}")
        return key

    def upload(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        safe_key = self._safe_key(key)
        path = self._root / safe_key
        path.parent.mkdir(parents=True, exist_ok=True)

        md5 = hashlib.md5()
        if isinstance(data, bytes):
            path.write_bytes(data)
            md5.update(data)
            size = len(data)
        else:
            with open(path, "wb") as file_obj:
                while chunk := data.read(8192):
                    file_obj.write(chunk)
                    md5.update(chunk)
            size = path.stat().st_size

        return StorageResult(
            key=key,
            size_bytes=size,
            content_type=content_type,
            checksum=md5.hexdigest(),
            storage_provider="local",
        )

    def download_url(self, key: str, expires_in: int = 3600) -> str:
        """Return a file path for local storage (not a real URL)."""
        _ = expires_in
        safe_key = self._safe_key(key)
        return str(self._root / safe_key)

    def download_bytes(self, key: str) -> bytes:
        return (self._root / self._safe_key(key)).read_bytes()

    def delete(self, key: str) -> bool:
        path = self._root / self._safe_key(key)
        if path.is_file():
            path.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        return (self._root / self._safe_key(key)).is_file()


class S3StorageBackend:
    """AWS S3 storage backend.

    Requires boto3. Install: pip install boto3

    Configure via environment:
        AWS_S3_BUCKET: Bucket name
        AWS_S3_REGION: Region (default: us-east-1)
        AWS_S3_PREFIX: Optional key prefix
    """

    def __init__(self) -> None:
        try:
            import boto3  # type: ignore[import-untyped]
        except ImportError as error:
            raise ImportError(
                "S3StorageBackend requires boto3. Install with: pip install boto3"
            ) from error

        self._bucket = os.environ["AWS_S3_BUCKET"]
        self._region = os.getenv("AWS_S3_REGION", "us-east-1")
        self._prefix = os.getenv("AWS_S3_PREFIX", "")
        self._client = boto3.client("s3", region_name=self._region)

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def upload(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        full_key = self._full_key(key)
        if isinstance(data, bytes):
            body = data
            size = len(data)
        else:
            body = data.read()
            size = len(body)

        md5 = hashlib.md5(body).hexdigest()
        self._client.put_object(
            Bucket=self._bucket,
            Key=full_key,
            Body=body,
            ContentType=content_type,
        )
        return StorageResult(
            key=key,
            size_bytes=size,
            content_type=content_type,
            checksum=md5,
            storage_provider="s3",
        )

    def download_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": self._full_key(key)},
            ExpiresIn=expires_in,
        )

    def download_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=self._full_key(key))
        return response["Body"].read()

    def delete(self, key: str) -> bool:
        self._client.delete_object(Bucket=self._bucket, Key=self._full_key(key))
        return True

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._full_key(key))
            return True
        except Exception:
            return False


class AzureBlobStorageBackend:
    """Azure Blob Storage backend.

    Requires azure-storage-blob. Install: pip install azure-storage-blob

    Configure via environment:
        AZURE_STORAGE_CONNECTION_STRING: Storage account connection string
        AZURE_STORAGE_CONTAINER: Container name
        AZURE_STORAGE_PREFIX: Optional blob prefix
    """

    def __init__(self) -> None:
        try:
            from azure.storage.blob import (  # type: ignore[import-untyped]
                BlobServiceClient,
                BlobSasPermissions,
                ContentSettings,
                generate_blob_sas,
            )
        except ImportError as error:
            raise ImportError(
                "AzureBlobStorageBackend requires azure-storage-blob. "
                "Install with: pip install azure-storage-blob"
            ) from error

        self._connection_string = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
        self._container = os.getenv("AZURE_STORAGE_CONTAINER", "artifacts")
        self._prefix = os.getenv("AZURE_STORAGE_PREFIX", "")
        self._client = BlobServiceClient.from_connection_string(self._connection_string)
        self._container_client = self._client.get_container_client(self._container)
        self._content_settings_cls = ContentSettings
        self._blob_sas_permissions_cls = BlobSasPermissions
        self._generate_blob_sas = generate_blob_sas

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def upload(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> StorageResult:
        full_key = self._full_key(key)
        if isinstance(data, bytes):
            body = data
            size = len(data)
        else:
            body = data.read()
            size = len(body)

        checksum = hashlib.md5(body).hexdigest()
        blob_client = self._container_client.get_blob_client(full_key)
        blob_client.upload_blob(
            body,
            overwrite=True,
            content_settings=self._content_settings_cls(content_type=content_type),
        )
        return StorageResult(
            key=key,
            size_bytes=size,
            content_type=content_type,
            checksum=checksum,
            storage_provider="azure_blob",
        )

    def download_url(self, key: str, expires_in: int = 3600) -> str:
        blob_name = self._full_key(key)
        blob_client = self._container_client.get_blob_client(blob_name)
        credential = getattr(self._client, "credential", None)
        account_key = getattr(credential, "account_key", None)
        account_name = getattr(self._client, "account_name", None)

        if account_key and account_name:
            expires_on = datetime.now(timezone.utc) + timedelta(seconds=max(1, expires_in))
            sas_token = self._generate_blob_sas(
                account_name=account_name,
                container_name=self._container,
                blob_name=blob_name,
                account_key=account_key,
                permission=self._blob_sas_permissions_cls(read=True),
                expiry=expires_on,
            )
            return f"{blob_client.url}?{sas_token}"

        return f"{blob_client.url}?se={max(1, expires_in)}"

    def download_bytes(self, key: str) -> bytes:
        blob_client = self._container_client.get_blob_client(self._full_key(key))
        return blob_client.download_blob().readall()

    def delete(self, key: str) -> bool:
        blob_client = self._container_client.get_blob_client(self._full_key(key))
        blob_client.delete_blob(delete_snapshots="include")
        return True

    def exists(self, key: str) -> bool:
        blob_client = self._container_client.get_blob_client(self._full_key(key))
        return bool(blob_client.exists())


def create_storage_backend() -> ArtifactStorageBackend:
    backend = os.getenv("STORAGE_BACKEND", "local")
    if backend == "local":
        return LocalStorageBackend()
    if backend == "s3":
        return S3StorageBackend()
    if backend == "azure_blob":
        return AzureBlobStorageBackend()
    raise ValueError(f"Unknown STORAGE_BACKEND: {backend}")


def _get_storage_backend() -> ArtifactStorageBackend:
    """Lazy singleton — created on first access, not at import time."""
    global _storage_backend  # noqa: PLW0603
    if _storage_backend is None:
        _storage_backend = create_storage_backend()
    return _storage_backend


_storage_backend: ArtifactStorageBackend | None = None


def get_storage_backend() -> ArtifactStorageBackend:
    """Public accessor for the storage backend singleton."""
    return _get_storage_backend()
