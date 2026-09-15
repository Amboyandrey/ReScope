"""Small helpers shared by API tests."""

from httpx import AsyncClient, Response

CSRF_COOKIE = "rescope_csrf"


async def signup(
    client: AsyncClient, email: str = "ada@example.com", password: str = "correct-horse-battery"
) -> Response:
    """Create an account through the API; the client keeps the resulting cookies."""
    return await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": password, "display_name": email.split("@")[0].title()},
    )


def csrf_headers(client: AsyncClient) -> dict[str, str]:
    """The header a mutating request must carry, echoing the CSRF cookie the client holds."""
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE, "") or ""}


async def create_tenant(client: AsyncClient, name: str = "Acme Inc", slug: str | None = None) -> Response:
    """Create a tenant through the API as whichever user the client is currently signed in as."""
    return await client.post(
        "/api/v1/tenants", json={"name": name, "slug": slug}, headers=csrf_headers(client)
    )


def tenant_headers(client: AsyncClient, slug: str) -> dict[str, str]:
    """The header that puts a request in a tenant's scope, on top of any CSRF header it also needs."""
    return {**csrf_headers(client), "X-Tenant-Slug": slug}
