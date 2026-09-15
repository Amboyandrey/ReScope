"""A member's own saved searches — personal, not shared across the tenant."""

from httpx import AsyncClient

from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers


async def test_create_list_delete_saved_search(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    created = await client.post(
        "/api/v1/tenants/current/saved-searches",
        json={"name": "Widget makers", "q": "widget manufacturer"},
        headers=headers,
    )
    assert created.status_code == 201
    saved = created.json()
    assert saved["name"] == "Widget makers"
    assert saved["q"] == "widget manufacturer"

    listed = await client.get("/api/v1/tenants/current/saved-searches", headers=headers)
    assert len(listed.json()) == 1

    deleted = await client.delete(f"/api/v1/tenants/current/saved-searches/{saved['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/tenants/current/saved-searches", headers=headers)).json() == []


async def test_saved_searches_are_personal_not_shared(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    await client.post(
        "/api/v1/tenants/current/saved-searches",
        json={"name": "Owner's search", "q": "widgets"},
        headers=headers,
    )

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "member@example.com", "role": "member"},
        headers=headers,
    )
    token = invite.json()["token"]
    client.cookies.clear()
    await signup(client, email="member@example.com")
    await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))

    member_headers = tenant_headers(client, tenant["slug"])
    listed = await client.get("/api/v1/tenants/current/saved-searches", headers=member_headers)
    assert listed.json() == []


async def test_cannot_delete_another_members_saved_search(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    saved = (
        await client.post(
            "/api/v1/tenants/current/saved-searches",
            json={"name": "Owner's search", "q": "widgets"},
            headers=headers,
        )
    ).json()

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "member@example.com", "role": "member"},
        headers=headers,
    )
    token = invite.json()["token"]
    client.cookies.clear()
    await signup(client, email="member@example.com")
    await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))

    member_headers = tenant_headers(client, tenant["slug"])
    response = await client.delete(
        f"/api/v1/tenants/current/saved-searches/{saved['id']}", headers=member_headers
    )
    assert response.status_code == 404
