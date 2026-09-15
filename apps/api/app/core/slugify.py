"""Turns a display name into a URL-safe slug — used for a tenant's subdomain."""

import re

# Subdomains the proxy or the platform itself already claims — a tenant can never take one of these.
RESERVED_SLUGS = {
    "www",
    "api",
    "app",
    "admin",
    "auth",
    "mail",
    "ftp",
    "root",
    "support",
    "help",
    "status",
    "docs",
    "blog",
    "static",
    "assets",
    "cdn",
    "t",
}


def slugify(text: str) -> str:
    """Lowercase, hyphenate, and strip anything that isn't alphanumeric."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "tenant"
