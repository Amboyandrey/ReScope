"""Tier 0 discovery — robots.txt, sitemap, and homepage-link scoring, against a fake transport.

`example.com` is used as the crawled host (as in ReCore's own crawl tests) because it's a real,
resolvable public domain — the SSRF guard's DNS lookup passes legitimately, while `MockTransport`
intercepts the actual HTTP traffic so the test never touches the real network.
"""

import httpx
import pytest

from app.scraping import discovery

_HOMEPAGE = """
<html><body>
<a href="/about">About us</a>
<a href="/products">Our products</a>
<a href="/careers">Careers</a>
<a href="https://other-host.example/x">Off-site link</a>
</body></html>
"""

_SITEMAP = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/services</loc></url>
  <url><loc>https://example.com/blog/2024-post</loc></url>
</urlset>
"""


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nDisallow: /careers")
    if path == "/sitemap.xml":
        return httpx.Response(200, text=_SITEMAP, headers={"content-type": "application/xml"})
    if path == "/":
        return httpx.Response(200, text=_HOMEPAGE, headers={"content-type": "text/html"})
    return httpx.Response(404)


@pytest.fixture(autouse=True)
def fake_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(discovery, "_transport", httpx.MockTransport(_handler))


async def test_homepage_is_always_first() -> None:
    urls = await discovery.discover_candidate_urls("https://example.com/")
    assert urls[0] == "https://example.com/"


async def test_keyword_matching_pages_outrank_unscored_ones() -> None:
    urls = await discovery.discover_candidate_urls("https://example.com/")
    assert "https://example.com/services" in urls
    assert "https://example.com/about" in urls
    assert "https://example.com/products" in urls
    # Scored 0 (no keyword match) — never returned, since only score > 0 candidates make the cut.
    assert "https://example.com/blog/2024-post" not in urls


async def test_robots_disallow_is_honored() -> None:
    urls = await discovery.discover_candidate_urls("https://example.com/")
    assert "https://example.com/careers" not in urls


async def test_off_host_links_are_never_included() -> None:
    urls = await discovery.discover_candidate_urls("https://example.com/")
    assert all("other-host.example" not in u for u in urls)


async def test_max_candidates_is_respected() -> None:
    urls = await discovery.discover_candidate_urls("https://example.com/", max_candidates=2)
    assert len(urls) <= 2


async def test_private_address_returns_no_candidates() -> None:
    assert await discovery.discover_candidate_urls("http://localhost/") == []
