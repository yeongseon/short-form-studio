import xml.etree.ElementTree as ET

import pytest

from creator_provider.image.groq_svg_provider import GroqSvgImageProvider


@pytest.mark.parametrize(
    "source",
    [
        '<svg><rect width="12" width="99"/></svg>',
        '<svg xmlns:xlink="http://www.w3.org/1999/xlink">'
        '<use xlink:href="#shape" xml:space="preserve" xml:lang="en"/></svg>',
        '<svg><!-- keep --><g id="first" id="second"><rect/></g></svg>',
    ],
)
def test_repaired_xml_preserves_first_attributes_when_model_duplicates(source: str) -> None:
    # Given / When
    repaired = GroqSvgImageProvider._repair_svg_xml(source)
    # Then
    root = ET.fromstring(repaired)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    child = root[0]
    assert child.attrib in ({"width": "12"}, {"href": "#shape"}, {"id": "first"})


def test_repair_preserves_safe_document_when_already_valid() -> None:
    # Given
    source = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="12"/></svg>'
    # When
    repaired = GroqSvgImageProvider._repair_svg_xml(source)
    # Then
    assert repaired == source
