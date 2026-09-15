"""Tier 1's render step — headless Chromium fetches a page the way a browser sees it (JavaScript
included), and its main content is converted to markdown so the extraction call gets structure
(headings, lists) instead of a wall of text.

One browser instance is shared across every page in a job — launching Chromium per page would
dwarf the actual page-load time. Every navigation is SSRF-guarded again immediately before it
happens: a candidate URL was already same-host-checked at discovery time, but DNS can change
between then and now, and Tier 0's own guard never ran against off-host redirect targets a page
might send a real browser through.
"""

import hashlib
from dataclasses import dataclass

from markdownify import markdownify
from playwright.async_api import Browser, Page, async_playwright

from app.core.ssrf import UnsafeUrlError, assert_safe_url

_NAV_TIMEOUT_MS = 15_000
_MAX_CONTENT_CHARS = 20_000
# Elements that are never part of a page's own content, dropped before markdown conversion so
# every fetched page doesn't repeat the same nav/footer boilerplate in the extraction prompt.
_STRIP_SELECTORS = "script, style, noscript, nav, footer, header, aside, svg"


@dataclass(frozen=True)
class RenderedPage:
    url: str
    final_url: str
    status_code: int | None
    markdown: str
    content_hash: str
    # Set only by Tier 2's visual agent (app/scraping/visual_agent.py) — Tier 1 never screenshots.
    screenshot: bytes | None = None


async def extract_markdown(page: Page) -> str | None:
    """Pull the current page's own content out (stripping nav/footer/script boilerplate) and
    convert it to markdown, or `None` if there's nothing worth keeping. Shared by Tier 1's
    render_page below and Tier 2's visual agent (app/scraping/visual_agent.py), which reads a
    page's content after clicking around rather than after a fresh navigation."""
    html = await page.evaluate(
        f"""() => {{
            const clone = document.body.cloneNode(true);
            clone.querySelectorAll("{_STRIP_SELECTORS}").forEach(el => el.remove());
            return clone.innerHTML;
        }}"""
    )
    markdown = markdownify(html, heading_style="ATX").strip()
    return markdown[:_MAX_CONTENT_CHARS] if markdown else None


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode()).hexdigest()


async def render_page(browser: Browser, url: str) -> RenderedPage | None:
    """Render one URL and return its markdown, or `None` if it wasn't safe or worth reading
    (blocked by SSRF, timed out, not HTML, or came back with nothing worth extracting)."""
    try:
        assert_safe_url(url)
    except UnsafeUrlError:
        return None

    page = await browser.new_page(user_agent="ReScope-Scraper/1.0")
    try:
        response = await page.goto(url, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
        if response is None:
            return None
        final_url = page.url
        try:
            assert_safe_url(final_url)  # the navigation may have redirected off the original host
        except UnsafeUrlError:
            return None
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return None

        markdown = await extract_markdown(page)
    except Exception:  # noqa: BLE001 — one bad page must never fail the whole job
        return None
    finally:
        await page.close()

    if not markdown:
        return None
    return RenderedPage(
        url=url,
        final_url=final_url,
        status_code=response.status,
        markdown=markdown,
        content_hash=content_hash(markdown),
    )


async def render_pages(urls: list[str]) -> list[RenderedPage]:
    """Render every URL with one shared browser instance, skipping any that fail individually."""
    pages: list[RenderedPage] = []
    async with async_playwright() as p:
        # --no-sandbox: the scraper container runs as a non-root user with no user-namespace
        # privileges to set up Chromium's own sandbox — the same requirement any non-privileged
        # Docker container has running Chromium, not a ReScope-specific loosening.
        browser = await p.chromium.launch(args=["--no-sandbox"])
        try:
            for url in urls:
                rendered = await render_page(browser, url)
                if rendered is not None:
                    pages.append(rendered)
        finally:
            await browser.close()
    return pages
