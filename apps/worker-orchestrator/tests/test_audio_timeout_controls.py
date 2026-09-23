from pathlib import Path
from unittest.mock import Mock

import pytest
from billiard.exceptions import SoftTimeLimitExceeded
from tasks import legacy_render_effects
from tasks.legacy_render_audio import AudioInputs
from tasks.legacy_render_contract import LegacyRequest


@pytest.mark.parametrize("step", [
    "generate_ambient_bgm", "mix_sfx_at_timestamps", "normalize_loudness",
])
def test_render_effects_keep_propagating_soft_timeout(
    step: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    # Given the real effects pipeline with only media operations replaced.
    for name in (
        "generate_ambient_bgm", "mix_audio_with_bgm", "mix_sfx_at_timestamps", "normalize_loudness",
    ):
        monkeypatch.setattr(
            legacy_render_effects.bgm_service, name, Mock(return_value=str(tmp_path / "audio.mp3")),
        )
    timeout = SoftTimeLimitExceeded()
    monkeypatch.setattr(legacy_render_effects.bgm_service, step, Mock(side_effect=timeout))
    # When an effect operation hits the real Celery soft limit.
    with pytest.raises(SoftTimeLimitExceeded) as raised:
        legacy_render_effects.mix_effects(
            LegacyRequest(1, "shorts_default", str(tmp_path)),
            AudioInputs(Path("audio.mp3"), None, [1, 1, 1, 1]), None,
        )
    # Then the already-fixed render path propagates unchanged.
    assert raised.value is timeout
