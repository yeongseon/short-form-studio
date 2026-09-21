"""SF-70: reusable CreativeProfile library for templates and drafts.

The six creative profiles live on the domain CreativeProfile model; this
service-layer library is the thin reusable resolver surface templates and drafts
share, DELEGATING to the domain presets (no copied factories) and exposing them
through the same typed, immutable contract as the other preset libraries
(sorted-tuple ids, ValidationError on bad ids). Style stays separate from recipe,
output, and encoding — the profile carries only look-and-feel fields — and there is
no implicit fallback: an unknown or legacy id raises loudly (wrapping the domain
ValueError, preserving its cause) so a saved project reproduces its exact style or
fails visibly.
"""

from __future__ import annotations

from creator_domain.exceptions import ValidationError
from creator_domain.models import CreativeProfile


def creative_profile_ids() -> tuple[str, ...]:
    """Return the shipped creative profile ids, sorted."""
    return tuple(CreativeProfile.preset_ids())


def resolve_creative_profile(profile_id: str) -> CreativeProfile:
    """Resolve a named creative profile by explicit id; unknown/blank/non-string raise.

    Delegates to the domain preset registry and wraps its ValueError as a typed
    ValidationError (preserving the cause), so there is never an implicit fallback:
    a saved project referencing an unknown or legacy id fails loudly.
    """
    if not isinstance(profile_id, str) or not profile_id:
        raise ValidationError(f"unknown creative profile: {profile_id!r}")
    try:
        return CreativeProfile.preset(profile_id)
    except ValueError as error:
        raise ValidationError(f"unknown creative profile: {profile_id!r}") from error


def creative_profile_library() -> dict[str, CreativeProfile]:
    """Enumerate the full reusable creative-profile library, freshly resolved."""
    return {profile_id: resolve_creative_profile(profile_id) for profile_id in creative_profile_ids()}
