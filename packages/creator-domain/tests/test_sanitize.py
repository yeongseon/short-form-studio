"""Tests for creator_domain.sanitize module."""
import pytest
from creator_domain.sanitize import UnsafePathComponent, sanitize_path_component


class TestSanitizePathComponent:
    """Test sanitize_path_component against various attack vectors."""

    # --- Valid IDs ---------------------------------------------------------

    def test_simple_alphanumeric(self):
        assert sanitize_path_component("section1") == "section1"

    def test_with_hyphens_and_underscores(self):
        assert sanitize_path_component("sec-01_intro") == "sec-01_intro"

    def test_with_dots_non_leading(self):
        assert sanitize_path_component("v1.2.3") == "v1.2.3"

    def test_uuid_style(self):
        val = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
        assert sanitize_path_component(val) == val

    # --- Path traversal attacks --------------------------------------------

    def test_rejects_dot_dot_slash(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("../../etc/passwd")

    def test_rejects_dot_dot_only(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("..")

    def test_rejects_embedded_dot_dot(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("foo..bar")

    def test_rejects_forward_slash(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("a/b")

    def test_rejects_backslash(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("a\\b")

    # --- Null byte ---------------------------------------------------------

    def test_rejects_null_byte(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("section\x00id")

    # --- Empty / too long --------------------------------------------------

    def test_rejects_empty(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("")

    def test_rejects_too_long(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("a" * 256)

    def test_accepts_max_length(self):
        val = "a" * 255
        assert sanitize_path_component(val) == val

    # --- Invalid characters ------------------------------------------------

    def test_rejects_leading_dot(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component(".hidden")

    def test_rejects_space(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("section 1")

    def test_rejects_semicolon(self):
        with pytest.raises(UnsafePathComponent):
            sanitize_path_component("a;b")

    # --- Custom label ------------------------------------------------------

    def test_custom_label_in_error_message(self):
        with pytest.raises(UnsafePathComponent, match="scene_id"):
            sanitize_path_component("", label="scene_id")
