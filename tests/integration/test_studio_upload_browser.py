from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from studio_proxy_runtime_support import StudioProxyRuntime, studio_proxy_runtime


def test_browser_recovers_after_nginx_rejects_oversized_image(
    tmp_path: Path,
    studio_proxy_runtime: StudioProxyRuntime,
) -> None:
    playwright = pytest.importorskip("playwright.sync_api", reason="Playwright is installed in browser CI")
    valid_image = tmp_path / "valid.png"
    oversized_image = tmp_path / "oversized.png"
    Image.new("RGB", (16, 16), (10, 20, 30)).save(valid_image, format="PNG")
    with oversized_image.open("wb") as stream:
        stream.truncate(26 * 1024 * 1024 + 1)

    with playwright.sync_playwright() as automation:
        browser = automation.chromium.launch()
        page = browser.new_page()
        page_errors: list[str] = []
        console_errors: list[str] = []
        failed_requests: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(f"{request.url}: {request.failure}"),
        )
        response = page.goto(
            f"{studio_proxy_runtime.origin}/browser-test/asset-upload.html"
            f"?workspaceId={studio_proxy_runtime.workspace_id}",
            wait_until="networkidle",
        )
        assert response is not None
        assert response.status == 200
        assert page.title() == "Studio asset upload browser test"
        upload = page.get_by_test_id("asset-file-input")
        assert upload.count() == 1, (
            f"page errors: {page_errors}; console errors: {console_errors}; "
            f"failed requests: {failed_requests}; content: {page.content()}"
        )

        upload.set_input_files(valid_image)
        page.get_by_test_id("asset-drop-zone").get_by_text("Placed valid.png").wait_for()

        upload.set_input_files(oversized_image)
        page.get_by_text(
            "Images can be up to 25 MiB. Choose a smaller file and try again.",
            exact=True,
        ).wait_for()

        upload.set_input_files(valid_image)
        page.get_by_test_id("asset-drop-zone").get_by_text("Placed valid.png").wait_for()
        browser.close()
