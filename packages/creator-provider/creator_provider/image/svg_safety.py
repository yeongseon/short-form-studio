"""XML policy for model-generated SVG before repair and after final cleanup."""

import re
import xml.etree.ElementTree as ET

from creator_provider.exceptions import ProviderError


def strip_svg_markup(svg: str) -> str:
    """Pre-parse cleanup retained for malformed model output; not the final policy."""
    svg = re.sub(r'<script[^>]*>.*?</script>', '', svg, flags=re.DOTALL | re.IGNORECASE)
    svg = re.sub(r'<script[^>]*/>', '', svg, flags=re.IGNORECASE)
    svg = re.sub(r'<foreignObject[^>]*>.*?</foreignObject>', '', svg, flags=re.DOTALL | re.IGNORECASE)
    svg = re.sub(r'<foreignObject[^>]*/>', '', svg, flags=re.IGNORECASE)
    svg = re.sub(r'\s+on\w+\s*=\s*"[^"]*"', '', svg, flags=re.IGNORECASE)
    svg = re.sub(r"\s+on\w+\s*=\s*'[^']*'", '', svg, flags=re.IGNORECASE)
    svg = re.sub(r'(href|src)\s*=\s*"\s*javascript:[^"]*"', r'\1=""', svg, flags=re.IGNORECASE)
    return re.sub(r'(href|src)\s*=\s*"\s*data:text/html[^"]*"', r'\1=""', svg, flags=re.IGNORECASE)


def reject_svg_declarations(svg: str) -> None:
    # Reject before any XML parse or repair can expand or discard a declaration.
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", svg, re.IGNORECASE):
        raise ProviderError("SVG DTD and entity declarations are disabled")


def parse_svg(svg: str) -> ET.Element:
    reject_svg_declarations(svg)
    return ET.fromstring(svg.encode("utf-8"))


def finalize_svg(svg: str) -> str:
    root = parse_svg(svg)
    if root.tag not in ("svg", "{http://www.w3.org/2000/svg}svg"):
        raise ProviderError("Expected SVG root")
    for parent in root.iter():
        for child in list(parent):
            if child.tag.rsplit("}", 1)[-1].lower() in ("script", "foreignobject"):
                parent.remove(child)
        for name, value in list(parent.attrib.items()):
            local_name = name.rsplit("}", 1)[-1].lower()
            if local_name.startswith("on"):
                del parent.attrib[name]
            elif local_name in ("href", "src") and value.strip().lower().startswith(
                ("javascript:", "data:text/html")
            ):
                parent.attrib[name] = ""
    return ET.tostring(root, encoding="unicode")
