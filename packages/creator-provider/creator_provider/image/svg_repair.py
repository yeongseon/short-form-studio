"""Pure repairs for common model-generated XML syntax errors."""

import re

from creator_provider.image.svg_safety import reject_svg_declarations


def repair_svg_xml(svg: str) -> str:
    reject_svg_declarations(svg)
    svg = re.sub(r'\s+xmlns:xlink="[^"]*"', "", svg)
    svg = svg.replace("xlink:href", "href")
    svg = re.sub(r'\s+xml:space="[^"]*"', "", svg)
    svg = re.sub(r'\s+xml:lang="[^"]*"', "", svg)
    if 'xmlns="http://www.w3.org/2000/svg"' not in svg:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return re.sub(r"<[^>]+>", deduplicate_attrs, svg)


def deduplicate_attrs(match: re.Match[str]) -> str:
    tag = match.group(0)
    if tag.startswith("</") or tag.startswith("<!--"):
        return tag

    attr_pattern = re.compile(r'(\s+)([\w\-]+(?::[\w\-]+)?)\s*=\s*"([^"]*)"')
    seen: dict[str, tuple[str, str, str]] = {}
    duplicates_found = False
    for attribute in attr_pattern.finditer(tag):
        ws, name, value = attribute.group(1), attribute.group(2), attribute.group(3)
        if name in seen:
            duplicates_found = True
        else:
            seen[name] = (ws, name, value)
    if not duplicates_found:
        return tag

    tag_start_match = re.match(r"(<\s*[\w\-]+)", tag)
    if not tag_start_match:
        return tag
    tag_name = tag_start_match.group(1)
    is_self_closing = tag.rstrip().endswith("/>")
    attrs_str = "".join(f' {name}="{value}"' for _, (_, name, value) in seen.items())
    if is_self_closing:
        return f"{tag_name}{attrs_str}/>"
    return f"{tag_name}{attrs_str}>"
