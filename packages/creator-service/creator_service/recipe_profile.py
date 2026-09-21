"""SF-15: explicit recipe/profile selection, replacing inline niche branches.

Worker tasks historically chose a QualityProfile with an inline niche fork
(``get_quality_profile(name if name != "shorts_default" else "ssul_v2")``). This
module makes that selection an explicit, testable mapping so behavior is driven
by configuration rather than scattered ``ssul``/``viral``/``facts`` branches in
core code. Legacy outputs are preserved.
"""

from __future__ import annotations

from creator_service.quality_profile import (
    QUALITY_PROFILES,
    QualityProfile,
    get_quality_profile,
)

# The historical niche default: the legacy pipeline mapped the neutral
# "shorts_default" render profile onto the ssul_v2 quality profile.
_LEGACY_NICHE_DEFAULT = "ssul_v2"

# Explicit recipe-id -> quality-profile-name mapping. Shipped short recipes map
# to concrete profiles instead of relying on a silent dict.get fallback.
_RECIPE_TO_PROFILE: dict[str, str] = {
    "shorts_default": _LEGACY_NICHE_DEFAULT,
    "shorts_general": "default",
    "shorts_story": "ssul_v2",
    "shorts_knowledge": "ssul_v2",
    "shorts_product": "default",
    "shorts_promotional": "default",
}


class UnknownProfileError(KeyError):
    """Raised when a recipe/profile id cannot be resolved in strict mode."""


def resolve_quality_profile(
    recipe_or_profile_id: str,
    *,
    strict: bool = False,
) -> QualityProfile:
    """Resolve a recipe/profile id to a concrete QualityProfile.

    Resolution order:
    1. A known recipe id maps to its configured quality profile.
    2. A direct quality-profile name resolves to that profile.
    3. Otherwise: raise in ``strict`` mode, else fall back to the legacy niche
       default (preserving pre-existing behavior for callers that relied on it).
    """
    profile_name = _RECIPE_TO_PROFILE.get(recipe_or_profile_id)
    if profile_name is not None:
        return get_quality_profile(profile_name)

    if recipe_or_profile_id in QUALITY_PROFILES:
        return get_quality_profile(recipe_or_profile_id)

    if strict:
        raise UnknownProfileError(
            f"Unknown recipe or profile id: {recipe_or_profile_id!r}"
        )
    return get_quality_profile(_LEGACY_NICHE_DEFAULT)
