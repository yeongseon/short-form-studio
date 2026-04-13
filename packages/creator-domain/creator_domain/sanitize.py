"""Path-component sanitisation utilities.

Any user-editable identifier (``section_id``, ``scene_id``, …) that ends up
in a filesystem path **must** pass through :func:`sanitize_path_component`
before being interpolated.  This prevents directory-traversal attacks such as
``../../etc/passwd`` being injected via crafted IDs.
"""

from __future__ import annotations

import re

# Only allow ASCII alphanumeric, hyphens, underscores, and dots (no leading dot).
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][\w.\-]*$")

# Maximum length for a single path component.
_MAX_COMPONENT_LENGTH = 255


class UnsafePathComponent(ValueError):
    """Raised when a path component fails sanitisation."""


def sanitize_path_component(value: str, *, label: str = "id") -> str:
    """Validate that *value* is safe to embed in a filesystem path.

    Parameters
    ----------
    value:
        The raw identifier string (e.g. a ``section_id``).
    label:
        Human-readable name used in error messages (e.g. ``"section_id"``).

    Returns
    -------
    str
        The validated *value*, unchanged.

    Raises
    ------
    UnsafePathComponent
        If the value contains path-traversal sequences, null bytes, slashes,
        or any character outside the safe set.
    """
    if not value:
        raise UnsafePathComponent(f"{label} must not be empty")

    if len(value) > _MAX_COMPONENT_LENGTH:
        raise UnsafePathComponent(
            f"{label} exceeds maximum length of {_MAX_COMPONENT_LENGTH}"
        )

    # Reject null bytes (could bypass C-level path functions).
    if "\x00" in value:
        raise UnsafePathComponent(f"{label} contains null byte")

    # Reject path separators and traversal patterns.
    if "/" in value or "\\" in value:
        raise UnsafePathComponent(f"{label} contains path separator")

    if ".." in value:
        raise UnsafePathComponent(f"{label} contains '..' traversal sequence")

    if not _SAFE_ID_RE.match(value):
        raise UnsafePathComponent(
            f"{label} contains invalid characters; "
            "only alphanumeric, hyphens, underscores, and dots (not leading) are allowed"
        )

    return value
