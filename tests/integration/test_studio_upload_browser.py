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
        page.goto(
            f"{studio_proxy_runtime.origin}/browser-test/asset-upload.html"
            f"?workspaceId={studio_proxy_runtime.workspace_id}",
        )
        upload = page.get_by_test_id("asset-file-input")

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
