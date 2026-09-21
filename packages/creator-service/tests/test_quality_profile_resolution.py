"""SF-17: remove the implicit shorts_default -> ssul_v2 fallback.

Default/legacy resolution must be explicit and documented; unknown ids must
raise rather than silently resolving to ssul_v2, but legacy stored runs that
reference known aliases (e.g. "shorts_default") stay reproducible.
"""

from __future__ import annotations

import pytest
from creator_service.quality_profile import (
    LEGACY_PROFILE_ALIASES,
    QualityProfile,
    UnknownQualityProfileError,
    get_quality_profile,
)


def test_known_profile_resolves() -> None:
    assert get_quality_profile("ssul_v2").name == "ssul_v2"
    assert get_quality_profile("default").name == "default"


def test_default_argument_is_explicit_ssul_v2() -> None:
    # The documented default remains ssul_v2 (explicit), preserving legacy runs.
    assert get_quality_profile().name == "ssul_v2"


def test_legacy_shorts_default_alias_resolves_reproducibly() -> None:
    # A legacy stored run referencing "shorts_default" must still resolve to the
    # same profile it always did (ssul_v2) via an explicit alias, not a silent
    # dict.get fallback.
    assert "shorts_default" in LEGACY_PROFILE_ALIASES
    assert get_quality_profile("shorts_default").name == "ssul_v2"


def test_unknown_name_raises_instead_of_silent_fallback() -> None:
    with pytest.raises(UnknownQualityProfileError):
        get_quality_profile("totally_unknown_profile")


def test_unknown_name_error_names_the_bad_id() -> None:
    with pytest.raises(UnknownQualityProfileError, match="mystery"):
        get_quality_profile("mystery")


def test_get_quality_profile_returns_quality_profile() -> None:
    assert isinstance(get_quality_profile("ssul_v2"), QualityProfile)
