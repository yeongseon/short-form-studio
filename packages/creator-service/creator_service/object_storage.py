import os


class _StorageBackend:
    def download_url(self, key: str) -> str:
        if not key:
            raise ValueError("Missing storage key")
        base_url = os.getenv("OBJECT_STORAGE_PUBLIC_BASE_URL", "").rstrip("/")
        if not base_url:
            raise RuntimeError("OBJECT_STORAGE_PUBLIC_BASE_URL is not configured")
        return f"{base_url}/{key.lstrip('/')}"


def get_storage_backend() -> _StorageBackend:
    return _StorageBackend()
