"""Tier 0 — no LLM, no browser: figure out which pages on a company's site are worth reading.

Reads robots.txt and sitemap.xml (both best-effort — a missing or malformed one just means fewer
candidates, never a failure), pulls every same-host link off the homepage, then ranks the combined
set by how much a URL's path or anchor text looks like it names a page ReScope actually cares
about. The homepage itself is always included and always ranked first, since even a site with
nothing else scorable still describes itself there.
"""

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup

from app.core.ssrf import UnsafeUrlError, assert_safe_url

USER_AGENT = "ReScope-Scraper/1.0 (+https://github.com/Amboyandrey/ReScope)"
_TIMEOUT = 15.0
_MAX_BODY_BYTES = 2 * 1024 * 1024

# Path segments and anchor words that mark a page as worth Tier 1's attention. Order doesn't
# matter — every match on a candidate URL adds one point, so a URL matching several counts more.
_KEYWORDS = [
    "about",
    "product",
    "service",
    "solution",
    "industr",
    "capabilit",
    "case-stud",
    "customer",
    "technology",
    "platform",
    "partner",
    "company",
    "what-we-do",
]

# Overridable only from tests, matching the seam app/knowledge/crawl.py gives itself in ReCore.
_transport: httpx.AsyncBaseTransport | None = None


@dataclass(frozen=True)
class Candidate:
    url: str
    score: int


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT, transport=_transport, headers={"User-Agent": USER_AGENT})


def _same_host(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.hostname) == (pb.scheme, pb.hostname)


def _score(url: str, anchor_text: str = "") -> int:
    haystack = f"{urlparse(url).path} {anchor_text}".lower()
    return sum(1 for kw in _KEYWORDS if kw in haystack)


async def _fetch_robots(client: httpx.AsyncClient, base_url: str) -> RobotFileParser:
    """Missing, unreachable, or malformed robots.txt is treated as allow-everything."""
    parsed = urlparse(base_url)
    parser = RobotFileParser()
    try:
        response = await client.get(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
        parser.parse(response.text.splitlines() if response.status_code < 400 else [])
    except httpx.HTTPError:
        parser.parse([])
    return parser


async def _fetch_sitemap_urls(client: httpx.AsyncClient, base_url: str) -> list[str]:
    """Best-effort `<loc>` extraction from `/sitemap.xml` — never raises on a missing or
    malformed sitemap, and ignores a sitemap index's own nested sitemaps rather than recursing."""
    parsed = urlparse(base_url)
    try:
        response = await client.get(f"{parsed.scheme}://{parsed.netloc}/sitemap.xml")
        if response.status_code >= 400:
            return []
        root = ElementTree.fromstring(response.content)
    except (httpx.HTTPError, ElementTree.ParseError):
        return []
    # Sitemap XML is namespaced; matching by local tag name sidesteps needing the exact URI.
    return [
        loc.text.strip()
        for loc in root.iter()
        if loc.tag.rsplit("}", 1)[-1] == "loc" and loc.text and loc.text.strip()
    ]


async def _fetch_homepage_links(client: httpx.AsyncClient, base_url: str) -> list[tuple[str, str]]:
    """`(url, anchor_text)` for every same-host link on the homepage — empty on any fetch failure."""
    try:
        response = await client.get(base_url)
        if response.status_code >= 400 or "text/html" not in response.headers.get("content-type", ""):
            return []
        body = response.content[:_MAX_BODY_BYTES]
    except httpx.HTTPError:
        return []
    soup = BeautifulSoup(body, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        raw_href = a["href"]
        if not isinstance(raw_href, str):  # bs4's stubs allow a multivalued attribute; href never is
            continue
        href = urljoin(base_url, raw_href)
        if _same_host(base_url, href):
            links.append((href.split("#")[0], a.get_text(" ", strip=True)))
    return links


async def discover_candidate_urls(website_url: str, *, max_candidates: int = 12) -> list[str]:
    """Rank a company's own pages by how likely each is to describe what it sells. The homepage
    is always first; everything after it is sorted by keyword score, ties broken by discovery
    order (sitemap first, then homepage links) so the result is deterministic."""
    try:
        assert_safe_url(website_url)
    except UnsafeUrlError:
        return []

    seen = {website_url}
    scored: list[Candidate] = []

    async with _client() as client:
        robots = await _fetch_robots(client, website_url)

        for url in await _fetch_sitemap_urls(client, website_url):
            if url in seen or not _same_host(website_url, url) or not robots.can_fetch(USER_AGENT, url):
                continue
            seen.add(url)
            scored.append(Candidate(url=url, score=_score(url)))

        for url, text in await _fetch_homepage_links(client, website_url):
            if url in seen or not robots.can_fetch(USER_AGENT, url):
                continue
            seen.add(url)
            scored.append(Candidate(url=url, score=_score(url, text)))

    scored.sort(key=lambda c: c.score, reverse=True)
    ranked = [website_url] + [c.url for c in scored if c.score > 0]
    return ranked[:max_candidates]
