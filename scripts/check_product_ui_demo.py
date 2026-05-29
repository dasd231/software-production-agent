"""Smoke-check the local product UI demo flow.

Usage:
    python scripts/check_product_ui_demo.py

Environment variables:
    PRODUCT_UI_URL      default http://127.0.0.1:7860
    PRODUCT_UI_USER     default showcase_admin
    PRODUCT_UI_PASSWORD default 12345678
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:  # pragma: no cover - operator helper
    raise SystemExit(f"Playwright is required: {exc}")

URL = os.getenv("PRODUCT_UI_URL", "http://127.0.0.1:7860").rstrip("/")
USER = os.getenv("PRODUCT_UI_USER", "showcase_admin")
PASSWORD = os.getenv("PRODUCT_UI_PASSWORD", "12345678")


def main() -> int:
    warnings: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 950}, device_scale_factor=1)
        page.on("console", lambda msg: warnings.append(f"console:{msg.type}:{msg.text}") if msg.type in {"error", "warning"} else None)
        page.on("pageerror", lambda exc: warnings.append(f"pageerror:{exc}"))

        page.goto(f"{URL}/login", wait_until="networkidle")
        if page.locator('input[name="username"]').count():
            page.fill('input[name="username"]', USER)
            page.fill('input[name="password"]', PASSWORD)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")

        page.goto(f"{URL}/", wait_until="networkidle")
        body = page.locator("body").inner_text()
        assert "输入需求，生成可预览软件" in body, "home page did not render"
        assert page.locator("#downloadBtn").is_disabled(), "download should be disabled before preview"

        page.click("#genBtn")
        page.wait_for_function("document.querySelector('#previewTitle').textContent !== '沙盒预览'", timeout=10_000)
        assert not page.locator("#downloadBtn").is_disabled(), "download should be enabled after preview"
        assert "成熟度" in page.locator("#deliveryGrid").inner_text(), "delivery metrics missing"

        with page.expect_download(timeout=8_000) as download_info:
            page.click("#downloadBtn")
        download = download_info.value
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / download.suggested_filename
            download.save_as(target)
            assert target.exists() and target.stat().st_size > 0, "downloaded ZIP is empty"

        page.get_by_role("button", name="方案库").click()
        page.wait_for_timeout(500)
        assert "成熟图书管理系统" in page.locator("body").inner_text(), "solution catalog missing curated demo"
        page.locator("#solutions").get_by_role("button", name="预览").first.click()
        page.wait_for_timeout(500)
        assert "图书" in page.locator("#previewTitle").inner_text(), "curated preview did not load"

        page.get_by_role("button", name="账户").click()
        page.wait_for_timeout(500)
        assert "个人中心和充值" in page.locator("body").inner_text(), "account page missing"
        assert page.locator("#balance").inner_text().strip(), "balance missing"
        browser.close()

    print("OK product UI demo smoke passed")
    if warnings:
        print("Warnings:")
        for item in warnings[:20]:
            print("-", item)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
