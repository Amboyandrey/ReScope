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
    return {"X-CSRF-Token": client.cookies.get(CSRF_COOKIE, "")}
