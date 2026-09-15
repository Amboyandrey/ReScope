"""Rejects a URL that resolves to an address outside the public internet.

Every domain a company is scraped from is supplied by a workspace member — a scraper that will
fetch whatever it's pointed at is a request-forgery primitive if unguarded: a member (malicious or
just careless) could point it at an internal service (a cloud metadata endpoint, an internal admin
panel, the API's own Redis) and use ReScope's outbound requests to reach it. This checks the
resolved address before a company is accepted and again before every fetch during scraping.

It does not pin the resolved address for the request that follows — a DNS answer could change
between this check and the actual HTTP call (a "TOCTOU" gap, closed via DNS rebinding). Closing
that fully means resolving once and connecting to the pinned IP for every request through this
domain, real extra plumbing left for a hardening pass; this still stops the overwhelmingly common
case, a domain that's simply misconfigured or maliciously chosen.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.errors import AppError


class UnsafeUrlError(AppError):
    """Raised when a URL is malformed or resolves to a disallowed address range."""

    status_code = 400
    detail = "This URL isn't allowed."


def _is_disallowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Report whether an address falls in a private, loopback, link-local, or reserved range."""
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_safe_url(url: str) -> None:
    """Resolve the URL's host and raise if any of its addresses are outside the public internet."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError("URL must start with http:// or https://.")
    if not parsed.hostname:
        raise UnsafeUrlError("URL must include a host.")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not resolve host: {parsed.hostname}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_disallowed(ip):
            raise UnsafeUrlError(f"URL resolves to a disallowed address: {ip}")
