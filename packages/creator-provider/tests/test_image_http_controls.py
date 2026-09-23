import json
from io import BytesIO
from unittest.mock import Mock

import anyio
import httpx
import pytest
from PIL import Image

from creator_provider.exceptions import ProviderAuthError, ProviderError, RateLimitError
from .test_image_http_boundaries import HttpCase, http_case as http_case


@pytest.mark.asyncio
async def test_png_output_when_http_succeeds(http_case: HttpCase, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a real renderer and a successful local HTTP response.
    case = http_case
    fetch = Mock(side_effect=AssertionError("Unexpected resource I/O"))
    monkeypatch.setattr("cairosvg.url.urlopen", fetch)
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect width="64" height="64" fill="red"/></svg>'
    stream = BytesIO()
    Image.new("RGB", (64, 64), "red").save(stream, format="PNG")
    case.handler.return_value = (
        httpx.Response(200, json={"choices": [{"message": {"content": svg}}]})
        if case.provider.model_key == "groq-svg" else
        httpx.Response(200, content=stream.getvalue(), headers={"content-type": "image/png"})
    )
    # When the adapter generates the output.
    result = await case.provider.generate("offline", {
        "output_path": str(case.output), "width": 64, "height": 64,
    })
    # Then a real PNG with the requested pixel content is produced without resource fetching.
    with Image.open(result.image_path) as image:
        image.load()
        assert image.format == "PNG"
        assert image.size == (64, 64)
        assert image.convert("RGB").getpixel((32, 32)) == (255, 0, 0)
    assert case.handler.call_count == 1
    fetch.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_case", ["groq"], indirect=True)
@pytest.mark.parametrize("response,error_type", [
    (httpx.Response(200, content=b"invalid JSON"), json.JSONDecodeError),
    (httpx.Response(200, json={}), KeyError),
    (httpx.Response(200, json={"choices": [{"message": {"content": "not SVG"}}]}), ProviderError),
])
async def test_invalid_groq_output_keeps_failure_semantics(
    http_case: HttpCase, response: httpx.Response, error_type: type[Exception],
) -> None:
    # Given malformed JSON, missing fields, or non-SVG content.
    http_case.handler.return_value = response
    # When the adapter consumes the response.
    with pytest.raises(error_type) as caught:
        await http_case.provider.generate("offline", {"output_path": str(http_case.output)})
    # Then the original failure class remains and no extra request occurs.
    assert type(caught.value) is error_type
    assert http_case.handler.call_count == 1
    assert not http_case.output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_case", ["hf"], indirect=True)
@pytest.mark.parametrize("status,error_type", [(401, ProviderAuthError), (429, RateLimitError)])
async def test_hf_fallback_preserves_http_failure(
    http_case: HttpCase, status: int, error_type: type[ProviderError],
) -> None:
    # Given a non-HTTP primary failure followed by an HTTP error on the existing fallback.
    http_case.handler.side_effect = [RuntimeError("primary failed"), httpx.Response(status, headers={"Retry-After": "17"})]
    # When the adapter invokes the fallback model.
    with pytest.raises(error_type) as caught:
        await http_case.provider.generate("offline", {"output_path": str(http_case.output)})
    # Then the fallback HTTP failure keeps its exact classification and metadata.
    assert type(caught.value) is error_type
    assert http_case.handler.call_count == 2
    http_case.sleep.assert_not_awaited()
    if status == 429:
        assert caught.value.retry_after == "17"
    assert not http_case.output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_case", ["hf"], indirect=True)
@pytest.mark.parametrize("status,error_type", [(401, ProviderAuthError), (429, RateLimitError), (503, ProviderError)])
async def test_hf_model_loading_retry_remains_bounded(
    http_case: HttpCase, status: int, error_type: type[ProviderError],
) -> None:
    # Given the existing loading retry followed by a terminal HTTP failure.
    http_case.handler.side_effect = [httpx.Response(503), httpx.Response(status, headers={"Retry-After": "17"})]
    # When generation retries the loading model once.
    with pytest.raises(error_type) as caught:
        await http_case.provider.generate("offline", {"output_path": str(http_case.output)})
    # Then no fallback swallows the second HTTP failure.
    assert type(caught.value) is error_type
    assert http_case.handler.call_count == 2
    http_case.sleep.assert_awaited_once_with(20)
    if status == 429:
        assert caught.value.retry_after == "17"


@pytest.mark.asyncio
@pytest.mark.parametrize("http_case", ["hf"], indirect=True)
async def test_hf_nonimage_content_keeps_provider_error(http_case: HttpCase) -> None:
    # Given an otherwise successful response with the wrong media type.
    http_case.handler.return_value = httpx.Response(200, json={"message": "not an image"})
    # When generation checks the response.
    with pytest.raises(ProviderError) as caught:
        await http_case.provider.generate("offline", {"output_path": str(http_case.output)})
    # Then the artifact rejection is unchanged and there is no fallback.
    assert type(caught.value) is ProviderError
    assert http_case.handler.call_count == 1
    assert not http_case.output.exists()


@pytest.mark.asyncio
async def test_cancellation_propagates_without_retry(http_case: HttpCase) -> None:
    # Given cancellation at the HTTP transport boundary.
    error = anyio.get_cancelled_exc_class()()
    http_case.handler.side_effect = error
    # When generation is cancelled.
    with pytest.raises(type(error)) as caught:
        await http_case.provider.generate("offline", {"output_path": str(http_case.output)})
    # Then cancellation identity survives without retry or sleep.
    assert caught.value is error
    assert http_case.handler.call_count == 1
    http_case.sleep.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_case", ["groq"], indirect=True)
async def test_groq_error_envelope_omits_sensitive_body(http_case: HttpCase) -> None:
    # Given a 200 error envelope echoing private input.
    http_case.handler.return_value = httpx.Response(200, json={"error": "synthetic-private-body"})
    # When the provider rejects the envelope.
    with pytest.raises(ProviderError) as caught:
        await http_case.provider.generate("offline", {"output_path": str(http_case.output)})
    # Then the existing generic error semantics remain without echoing the body.
    assert type(caught.value) is ProviderError
    assert "synthetic-private-body" not in str(caught.value)
    assert http_case.handler.call_count == 1
