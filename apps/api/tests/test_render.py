"""Tier 1 rendering, against the real network — Playwright has no transport-mocking seam the way
httpx does, so this exercises real Chromium against `example.com` (stable, minimal, and exactly
what CI's own `playwright install chromium` step exists to support)."""

from playwright.async_api import async_playwright

from app.scraping.render import render_page, render_pages


async def test_render_pages_returns_markdown_for_a_real_page() -> None:
    pages = await render_pages(["https://example.com"])
    assert len(pages) == 1
    assert pages[0].status_code == 200
    assert "Example Domain" in pages[0].markdown


async def test_render_pages_skips_a_page_that_isnt_worth_reading() -> None:
    # A private address is rejected by the SSRF guard before Chromium ever navigates to it.
    pages = await render_pages(["http://localhost:1"])
    assert pages == []


async def test_render_page_rejects_unsafe_url_directly() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            assert await render_page(browser, "http://169.254.169.254/") is None
        finally:
            await browser.close()
