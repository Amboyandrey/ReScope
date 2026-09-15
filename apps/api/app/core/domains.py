"""Turns whatever a member pastes — a bare domain, or a full URL with a path — into the
`(domain, website_url)` pair every company row is keyed and displayed by."""

import re
from urllib.parse import urlparse

from app.core.errors import InvalidDomain

# A dot is common but not required — "localhost" and other single-label hosts are syntactically
# valid hostnames too. Whether a host is actually a safe address to fetch is the SSRF guard's
# job (app/core/ssrf.py), not this regex's — conflating the two would let format validation
# quietly stand in for a security check it was never designed to be.
_DOMAIN_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$")


def normalize_domain(raw: str) -> tuple[str, str]:
    """Return `(domain, website_url)`, e.g. `"https://www.Acme.com/about"` -> `("acme.com",
    "https://acme.com")`. Raises `InvalidDomain` for anything that isn't a plausible hostname."""
    candidate = raw.strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if not host or not _DOMAIN_RE.match(host):
        raise InvalidDomain()
    scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
    return host, f"{scheme}://{host}"
