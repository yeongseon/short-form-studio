from pathlib import Path

import pytest

from tasks.runtime_topology_probe import _evidence_file, _provider_url


def test_evidence_file_rejects_path_outside_configured_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Given a configured evidence root and a traversal destination.
    monkeypatch.setenv("WORKER_TOPOLOGY_EVIDENCE_DIR", str(tmp_path))

    # When the probe resolves the destination.
    with pytest.raises(ValueError, match="evidence"):
        _evidence_file("../outside.json")


def test_provider_url_rejects_unconfigured_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a CI-owned provider origin.
    monkeypatch.setenv("WORKER_TOPOLOGY_PROVIDER_URL", "http://host.docker.internal:8123")

    # When a broker message attempts to redirect the probe elsewhere.
    with pytest.raises(ValueError, match="provider"):
        _provider_url("http://169.254.169.254/latest/meta-data")


def test_provider_url_accepts_only_exact_configured_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a CI-owned provider origin.
    configured = "http://host.docker.internal:8123"
    monkeypatch.setenv("WORKER_TOPOLOGY_PROVIDER_URL", configured)

    # When the exact configured origin is parsed.
    assert _provider_url(configured) == configured
