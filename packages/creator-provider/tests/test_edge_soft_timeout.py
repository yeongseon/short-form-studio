from pathlib import Path

import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from creator_provider.exceptions import ProviderError
from creator_provider.tts.edge_tts_provider import EdgeTTSProvider


@pytest.mark.asyncio
async def test_edge_sdk_soft_timeout_is_not_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an Edge SDK save interrupted by the worker soft deadline.
    calls: list[str] = []

    class FakeCommunicate:
        def __init__(self, **kwargs: str) -> None:
            assert kwargs["voice"] == "ko-KR-SunHiNeural"

        async def save(self, path: str) -> None:
            calls.append(path)
            raise SoftTimeLimitExceeded()

    monkeypatch.setattr("creator_provider.tts.edge_tts_provider.edge_tts.Communicate", FakeCommunicate)
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    output = tmp_path / "timeout.mp3"
    # When the adapter awaits the real SDK boundary.
    with pytest.raises(SoftTimeLimitExceeded):
        await EdgeTTSProvider(endpoint="", model_key="edge-tts").generate(
            "hello", params={"output_path": str(output)},
        )
    # Then the caller receives the timeout identity and only one save was attempted.
    assert calls == [str(output)]
    assert not output.exists()


@pytest.mark.asyncio
async def test_edge_other_sdk_failures_remain_provider_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given an unrelated SDK failure.
    class FakeCommunicate:
        def __init__(self, **kwargs: str) -> None:
            pass

        async def save(self, path: str) -> None:
            raise RuntimeError("SDK failed")

    monkeypatch.setattr("creator_provider.tts.edge_tts_provider.edge_tts.Communicate", FakeCommunicate)
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    # When generation fails.
    with pytest.raises(ProviderError):
        await EdgeTTSProvider(endpoint="", model_key="edge-tts").generate(
            "hello", params={"output_path": str(tmp_path / "other.mp3")},
        )
