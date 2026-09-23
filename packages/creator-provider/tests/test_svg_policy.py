import xml.etree.ElementTree as ET

import pytest

from creator_provider.exceptions import ProviderError
from creator_provider.image.svg_safety import finalize_svg, parse_svg


@pytest.mark.parametrize("declaration", [
    '<!DOCTYPE svg [<!ENTITY payload "expanded">]>',
    '<!DOCTYPE svg SYSTEM "file:///synthetic/schema">',
])
def test_policy_rejects_declarations_when_parsed_directly(declaration: str) -> None:
    # Given
    source = declaration + '<svg><text>&payload;</text></svg>'
    # When / Then
    with pytest.raises(ProviderError, match="DTD"):
        parse_svg(source)


def test_final_policy_preserves_shape_when_removing_namespaced_foreign_content() -> None:
    # Given
    source = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:s="http://www.w3.org/2000/svg">'
        '<s:foreignObject><rect fill="blue"/></s:foreignObject>'
        '<rect fill="red" s:onload="synthetic()"/></svg>'
    )
    # When
    result = ET.fromstring(finalize_svg(source))
    # Then
    assert len(result) == 1
    assert result[0].tag == '{http://www.w3.org/2000/svg}rect'
    assert result[0].attrib == {"fill": "red"}


def test_final_policy_rejects_non_svg_root_when_xml_is_well_formed() -> None:
    # Given / When / Then
    with pytest.raises(ProviderError, match="SVG root"):
        finalize_svg('<html><svg/></html>')
