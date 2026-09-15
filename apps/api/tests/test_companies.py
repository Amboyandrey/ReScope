"""Adding, listing, viewing, and deleting companies — plus the SSRF guard on the domain field."""

from httpx import AsyncClient

from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers


async def _setup_tenant(
    client: AsyncClient, email: str = "ada@example.com", tenant_name: str = "Acme Inc"
) -> dict[str, str]:
    await signup(client, email=email)
    tenant = (await create_tenant(client, name=tenant_name)).json()
    return tenant_headers(client, tenant["slug"])


async def test_create_company_normalizes_domain(client: AsyncClient) -> None:
    headers = await _setup_tenant(client)
    response = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "https://www.Example.com/about"}, headers=headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["domain"] == "example.com"
    assert body["website_url"] == "https://example.com"
    assert body["profile_status"] == "pending"


async def test_duplicate_domain_in_same_tenant_is_rejected(client: AsyncClient) -> None:
    headers = await _setup_tenant(client)
    await client.post("/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers)
    response = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    assert response.status_code == 409


async def test_invalid_domain_is_rejected(client: AsyncClient) -> None:
    headers = await _setup_tenant(client)
    response = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "not a domain"}, headers=headers
    )
    assert response.status_code == 422


async def test_private_address_is_rejected(client: AsyncClient) -> None:
    headers = await _setup_tenant(client)
    response = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "localhost"}, headers=headers
    )
    assert response.status_code == 400


async def test_list_and_get_and_delete(client: AsyncClient) -> None:
    headers = await _setup_tenant(client)
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]

    listed = await client.get("/api/v1/tenants/current/companies", headers=headers)
    assert len(listed.json()) == 1

    detail = await client.get(f"/api/v1/tenants/current/companies/{company_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["offerings"] == []
    assert detail.json()["competencies"] == []

    deleted = await client.delete(f"/api/v1/tenants/current/companies/{company_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/tenants/current/companies", headers=headers)).json() == []


async def test_viewer_cannot_add_a_company(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "viewer@example.com", "role": "viewer"},
        headers=headers,
    )
    token = invite.json()["token"]
    client.cookies.clear()
    await signup(client, email="viewer@example.com")
    await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))

    response = await client.post(
        "/api/v1/tenants/current/companies",
        json={"domain": "example.com"},
        headers=tenant_headers(client, tenant["slug"]),
    )
    assert response.status_code == 403


async def test_companies_are_isolated_between_tenants(client: AsyncClient) -> None:
    headers_a = await _setup_tenant(client, email="owner-a@example.com", tenant_name="Tenant A")
    await client.post("/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers_a)
    client.cookies.clear()

    headers_b = await _setup_tenant(client, email="owner-b@example.com", tenant_name="Tenant B")
    listed_b = await client.get("/api/v1/tenants/current/companies", headers=headers_b)
    assert listed_b.json() == []
