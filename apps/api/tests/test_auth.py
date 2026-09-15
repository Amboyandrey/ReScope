"""Signup, login, logout, sessions, CSRF and rate limiting."""

from httpx import AsyncClient

from tests.helpers import csrf_headers, signup


async def test_signup_sets_domain_scoped_cookies_and_returns_user(client: AsyncClient) -> None:
    response = await signup(client)
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "ada@example.com"
    assert "password_hash" not in body
    set_cookie = "\n".join(response.headers.get_list("set-cookie"))
    assert "rescope_session=" in set_cookie and "HttpOnly" in set_cookie
    assert "Domain=.rescope.localhost" in set_cookie
    assert "rescope_csrf=" in set_cookie


async def test_me_requires_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    await signup(client)
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["display_name"] == "Ada"


async def test_duplicate_email_is_rejected(client: AsyncClient) -> None:
    await signup(client)
    client.cookies.clear()
    response = await signup(client, email="ADA@example.com")
    assert response.status_code == 409


async def test_login_wrong_password_and_unknown_email_look_the_same(client: AsyncClient) -> None:
    await signup(client)
    client.cookies.clear()
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "nope-nope-nope"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_login_then_logout_revokes_the_session(client: AsyncClient) -> None:
    await signup(client)
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login", json={"email": "ada@example.com", "password": "correct-horse-battery"}
    )
    assert login.status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    session_cookie = client.cookies.get("rescope_session")

    logout = await client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 204
    # Even if a copy of the old cookie is replayed, the session is gone from Redis.
    client.cookies.set("rescope_session", session_cookie or "", domain=".rescope.localhost")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_mutating_request_without_csrf_header_is_rejected(client: AsyncClient) -> None:
    await signup(client)
    assert (await client.post("/api/v1/auth/logout")).status_code == 403
    assert (await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"})).status_code == 403


async def test_auth_is_rate_limited_per_email(client: AsyncClient) -> None:
    statuses = []
    for _ in range(6):
        r = await client.post("/api/v1/auth/login", json={"email": "ada@example.com", "password": "x" * 12})
        statuses.append(r.status_code)
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429


async def test_weak_password_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/signup", json={"email": "a@example.com", "password": "short", "display_name": "A"}
    )
    assert response.status_code == 422
