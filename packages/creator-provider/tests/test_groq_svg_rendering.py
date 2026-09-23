"""Real Cairo PNG regressions; only the paid LLM HTTP transport is synthetic."""

from functools import partial
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree as ET

import anyio
import httpx
import pytest
from PIL import Image

from creator_provider.image.groq_svg_provider import GroqSvgImageProvider
from creator_provider.exceptions import ProviderError

SAFE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" fill="#ff0000"/></svg>'
)
MALFORMED_SVG = SAFE_SVG.replace(
    'viewBox=', 'bad:attr="x" onload="synthetic()" viewBox='
).replace('<rect', '<script>synthetic()</script><rect')


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> GroqSvgImageProvider:
    monkeypatch.setenv("GROQ_API_KEY", "synthetic")
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    return GroqSvgImageProvider("local", "groq-svg")


@pytest.fixture
def llm_response(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    responses = [SAFE_SVG]

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": responses[0]}}]}, request=request
        )

    monkeypatch.setattr(
        httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(respond))
    )
    return responses


@pytest.fixture(autouse=True)
def resource_fetch(monkeypatch: pytest.MonkeyPatch) -> Mock:
    import cairosvg.url

    fetch = Mock(side_effect=AssertionError("Unexpected resource I/O"))
    monkeypatch.setattr(cairosvg.url, "urlopen", fetch)
    return fetch


def test_generates_decodable_png_when_llm_returns_safe_svg(
    provider: GroqSvgImageProvider, llm_response: list[str], tmp_path: Path
) -> None:
    # Given: actual provider, synthetic HTTP response, actual installed CairoSVG.
    output = tmp_path / "safe.png"
    # When
    result = anyio.run(
        provider.generate, "synthetic", {"width": 64, "height": 64, "output_path": str(output)}
    )
    # Then: full decoding and pixel output, not just a mocked renderer or PNG header.
    with Image.open(result.image_path) as image:
        image.load()
        assert image.format == "PNG"
        assert image.size == (64, 64)
        assert image.convert("RGB").getpixel((32, 32)) == (255, 0, 0)


def test_final_sanitization_when_namespace_repair_exhausts_retries(
    provider: GroqSvgImageProvider, llm_response: list[str]
) -> None:
    # Given: sanitization succeeds but parsing needs the last-resort namespace repair.
    llm_response[0] = MALFORMED_SVG
    # When
    result = anyio.run(provider._generate_valid_svg, "synthetic", 64, 64)
    # Then: recovered shape survives without reintroducing discarded markup.
    root = ET.fromstring(result)
    assert [node.tag.rsplit("}", 1)[-1] for node in root.iter()] == ["svg", "rect"]
    assert all(not name.lower().startswith("on") for node in root.iter() for name in node.attrib)


@pytest.mark.parametrize("resource", [
    "https://resource.invalid/image", "file:///synthetic/image", "relative.svg",
    "data:image/svg+xml,%3Csvg/%3E",
])
@pytest.mark.parametrize(
    "markup",
    [
        '<image href="{resource}" width="64" height="64"/>',
        '<image xlink:href="{resource}" width="64" height="64"/>',
        '<use href="{resource}#shape"/>',
        '<text><tref href="{resource}#text"/></text>',
        '<style>@import url({resource});</style>',
        '<style>@import "{resource}";</style>',
    ],
)
def test_denies_resource_when_renderer_requests_external_content(
    provider: GroqSvgImageProvider, llm_response: list[str], resource_fetch: Mock,
    resource: str, markup: str,
) -> None:
    # Given
    llm_response[0] = SAFE_SVG.replace('</svg>', markup.format(resource=resource) + '</svg>')
    # When / Then
    with pytest.raises(ProviderError, match="resource loading is disabled"):
        anyio.run(provider.generate, "synthetic", {"width": 64, "height": 64})
    resource_fetch.assert_not_called()


@pytest.mark.parametrize(
    "declaration",
    [
        '<!DOCTYPE svg>',
        '<!DOCTYPE svg SYSTEM "https://resource.invalid/schema">',
        '<!DOCTYPE svg [<!ENTITY payload "expanded">]>',
        '<!DOCTYPE svg [<!ENTITY payload SYSTEM "file:///synthetic/entity">]>',
    ],
)
def test_rejects_dtd_before_repair_can_expand_entities(
    provider: GroqSvgImageProvider, llm_response: list[str], declaration: str
) -> None:
    # Given
    llm_response[0] = declaration + SAFE_SVG.replace('</svg>', '<text>&payload;</text></svg>')
    # When / Then
    with pytest.raises(ProviderError, match="DTD"):
        anyio.run(provider._generate_valid_svg, "synthetic", 64, 64)


@pytest.mark.parametrize(
    "markup",
    [
        '<s:script xmlns:s="http://www.w3.org/2000/svg">synthetic()</s:script>',
        '<g xmlns:s="http://www.w3.org/2000/svg" s:onload="synthetic()"/>',
        "<a href='javascript:synthetic()'/>",
        '<a href="java&#x73;cript:synthetic()"/>',
    ],
)
def test_final_sanitizer_handles_xml_namespaces_and_decoded_attributes(
    provider: GroqSvgImageProvider, llm_response: list[str], markup: str
) -> None:
    # Given
    llm_response[0] = SAFE_SVG.replace('</svg>', markup + '</svg>')
    # When
    result = anyio.run(provider._generate_valid_svg, "synthetic", 64, 64)
    # Then
    root = ET.fromstring(result)
    assert all(node.tag.rsplit('}', 1)[-1].lower() != "script" for node in root.iter())
    assert all(
        not name.rsplit('}', 1)[-1].lower().startswith('on')
        and not value.lower().startswith('javascript:')
        for node in root.iter() for name, value in node.attrib.items()
    )


@pytest.mark.parametrize("markup", [
    '<style>@import url("https://resource.invalid/ignored.css");</style>',
    '<rect width="1" height="1" fill="url(https://resource.invalid/paint)"/>',
    '<rect width="1" height="1" style="fill:url(file:///synthetic/paint)"/>',
    '<?xml-stylesheet href="https://resource.invalid/style.css"?>',
    '<g src="file:///synthetic/ignored"/>',
])
def test_ignored_resource_syntax_stays_inert_when_rasterized(
    provider: GroqSvgImageProvider, llm_response: list[str], tmp_path: Path,
    resource_fetch: Mock, markup: str,
) -> None:
    # Given
    llm_response[0] = SAFE_SVG.replace('</svg>', markup + '</svg>')
    # When
    result = anyio.run(provider.generate, "synthetic", {
        "width": 64, "height": 64, "output_path": str(tmp_path / "inert.png"),
    })
    # Then
    with Image.open(result.image_path) as image:
        image.load()
        assert image.convert("RGB").getpixel((32, 32)) == (255, 0, 0)
    resource_fetch.assert_not_called()


def test_local_fragment_shapes_and_css_gradients_render_when_self_contained(
    provider: GroqSvgImageProvider, llm_response: list[str], tmp_path: Path,
    resource_fetch: Mock,
) -> None:
    # Given
    llm_response[0] = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<defs><linearGradient id="red"><stop stop-color="red"/></linearGradient>'
        '<rect id="shape" width="64" height="64"/></defs>'
        '<style>.paint {fill:url(#red)}</style><use href="#shape" class="paint"/></svg>'
    )
    # When
    result = anyio.run(provider.generate, "synthetic", {
        "width": 64, "height": 64, "output_path": str(tmp_path / "fragment.png"),
    })
    # Then
    with Image.open(result.image_path) as image:
        image.load()
        assert image.convert("RGB").getpixel((32, 32)) == (255, 0, 0)
    resource_fetch.assert_not_called()


@pytest.mark.parametrize("source", [MALFORMED_SVG, '<svg><broken>'])
def test_recovered_and_ultimate_fallbacks_produce_png_when_xml_is_malformed(
    provider: GroqSvgImageProvider, llm_response: list[str], tmp_path: Path, source: str,
) -> None:
    # Given
    llm_response[0] = source
    # When
    result = anyio.run(provider.generate, "synthetic", {
        "width": 64, "height": 64, "output_path": str(tmp_path / "fallback.png"),
    })
    # Then
    with Image.open(result.image_path) as image:
        image.load()
        assert image.format == "PNG"
        assert image.size == (64, 64)
        assert image.convert("RGB").getbbox() == (0, 0, 64, 64)


def test_dimension_bounds_apply_when_actual_cairo_renders(
    provider: GroqSvgImageProvider, llm_response: list[str], tmp_path: Path,
) -> None:
    # Given / When
    result = anyio.run(provider.generate, "synthetic", {
        "width": 999999, "height": -1, "output_path": str(tmp_path / "bounded.png"),
    })
    # Then
    with Image.open(result.image_path) as image:
        image.load()
        assert image.size == (2048, 64)
    assert (result.width, result.height) == (2048, 64)


def test_output_confinement_applies_after_real_render(
    provider: GroqSvgImageProvider, llm_response: list[str], tmp_path: Path,
) -> None:
    # Given
    output = tmp_path / ".." / "outside.png"
    # When / Then
    with pytest.raises(ValueError):
        anyio.run(provider.generate, "synthetic", {
            "width": 64, "height": 64, "output_path": str(output),
        })
    assert not output.exists()
