from __future__ import annotations

from pathlib import Path

import pytest

from studio_proxy_runtime_support import StudioProxyRuntime, studio_proxy_runtime


def test_browser_recovers_after_nginx_rejects_oversized_image(
    tmp_path: Path,
    studio_proxy_runtime: StudioProxyRuntime,
) -> None:
    playwright = pytest.importorskip("playwright.sync_api", reason="Playwright is installed in browser CI")
    valid_image = tmp_path / "valid.png"
    oversized_image = tmp_path / "oversized.png"
    valid_image.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00"
        b"\x03\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
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
