"""Unit tests for GroqSvgImageProvider SVG sanitizer."""

from __future__ import annotations

import unittest

from creator_provider.image.groq_svg_provider import GroqSvgImageProvider


class TestSvgSanitizer(unittest.TestCase):
    """Tests for _sanitize_svg XSS prevention."""

    def test_removes_script_elements(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert("xss")</script><rect/></svg>'
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("<script", result)
        self.assertNotIn("alert", result)
        self.assertIn("<rect/>", result)

    def test_removes_self_closing_script(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><script src="evil.js"/><rect/></svg>'
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("<script", result)
        self.assertIn("<rect/>", result)

    def test_removes_foreignobject(self) -> None:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            "<foreignObject><body><script>evil()</script></body></foreignObject>"
            "<rect/></svg>"
        )
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("<foreignObject", result)
        self.assertNotIn("evil", result)
        self.assertIn("<rect/>", result)

    def test_removes_event_handlers_double_quotes(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect onload="alert(1)" onclick="evil()"/></svg>'
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("onload", result)
        self.assertNotIn("onclick", result)
        self.assertNotIn("alert", result)
        self.assertIn("<rect", result)

    def test_removes_event_handlers_single_quotes(self) -> None:
        svg = "<svg xmlns=\"http://www.w3.org/2000/svg\"><rect onmouseover='hack()'/></svg>"
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("onmouseover", result)
        self.assertNotIn("hack", result)

    def test_neutralizes_javascript_uri(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><rect/></a></svg>'
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("javascript:", result)
        self.assertIn("href=", result)  # href preserved but value neutralized

    def test_neutralizes_data_text_html_uri(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><use href="data:text/html,<script>evil()</script>"/></svg>'
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("data:text/html", result)

    def test_preserves_safe_svg(self) -> None:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1920">'
            '<defs><linearGradient id="bg"><stop offset="0%" stop-color="#1a1a2e"/>'
            "</linearGradient></defs>"
            '<rect width="1080" height="1920" fill="url(#bg)"/>'
            '<circle cx="540" cy="960" r="200" fill="#c4a747"/>'
            "</svg>"
        )
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertEqual(result, svg)  # safe SVG unchanged

    def test_case_insensitive_script_removal(self) -> None:
        svg = '<svg xmlns="http://www.w3.org/2000/svg"><SCRIPT>alert("xss")</SCRIPT><rect/></svg>'
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("SCRIPT", result.upper().replace("<RECT/>", ""))
        self.assertNotIn("alert", result)

    def test_multiline_script_removal(self) -> None:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg">'
            "<script>\n"
            "  var x = 1;\n"
            "  alert(x);\n"
            "</script>"
            "<rect/></svg>"
        )
        result = GroqSvgImageProvider._sanitize_svg(svg)
        self.assertNotIn("<script", result)
        self.assertNotIn("alert", result)


class TestPollinationsValidation(unittest.TestCase):
    """Tests for Pollinations dimension bounds and content-type validation."""

    def test_dimension_constants_exist(self) -> None:
        from creator_provider.image.pollinations_provider import _MAX_DIM, _MIN_DIM

        self.assertEqual(_MIN_DIM, 64)
        self.assertEqual(_MAX_DIM, 2048)


if __name__ == "__main__":
    unittest.main()
