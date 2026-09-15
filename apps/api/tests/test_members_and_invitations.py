"""Members: listing, role changes, removal, and the last-owner invariant. Invitations end to end."""

from httpx import AsyncClient

from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers


async def test_owner_is_the_only_member_right_after_creation(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    response = await client.get("/api/v1/tenants/current/members", headers=headers)
    assert response.status_code == 200
    [member] = response.json()
    assert member["role"] == "owner"


async def test_owner_cannot_be_removed_when_they_are_the_last_one(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    me = (await client.get("/api/v1/auth/me")).json()
    response = await client.delete(
        f"/api/v1/tenants/current/members/{me['id']}", headers=tenant_headers(client, tenant["slug"])
    )
    assert response.status_code == 409


async def test_invite_accept_and_role_enforcement(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "member@example.com", "role": "member"},
        headers=headers,
    )
    assert invite.status_code == 201
    token = invite.json()["token"]
    assert token

    preview = await client.get(f"/api/v1/invitations/{token}")
    assert preview.status_code == 200
    assert preview.json()["tenant_name"] == tenant["name"]

    client.cookies.clear()
    await signup(client, email="member@example.com")
    accept = await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))
    assert accept.status_code == 200
    assert accept.json()["role"] == "member"

    # A member can't invite anyone else — only admin/owner may.
    forbidden = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "third@example.com", "role": "member"},
        headers=tenant_headers(client, tenant["slug"]),
    )
    assert forbidden.status_code == 403


async def test_only_owner_can_invite_as_owner(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "admin@example.com", "role": "admin"},
        headers=headers,
    )
    token = invite.json()["token"]
    client.cookies.clear()
    await signup(client, email="admin@example.com")
    await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))

    forbidden = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "owner2@example.com", "role": "owner"},
        headers=tenant_headers(client, tenant["slug"]),
    )
    assert forbidden.status_code == 403


async def test_expired_or_unknown_token_is_invalid(client: AsyncClient) -> None:
    response = await client.get("/api/v1/invitations/not-a-real-token")
    assert response.status_code == 400


async def test_pending_invitations_for_my_email(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "invitee@example.com", "role": "member"},
        headers=tenant_headers(client, tenant["slug"]),
    )
    client.cookies.clear()

    await signup(client, email="invitee@example.com")
    pending = await client.get("/api/v1/invitations/pending")
    assert pending.status_code == 200
    [item] = pending.json()
    assert item["tenant_name"] == tenant["name"]
