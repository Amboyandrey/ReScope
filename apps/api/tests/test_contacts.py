"""A company's contacts — CRUD, permissions, and tenant isolation."""

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def _setup_company(client: AsyncClient) -> tuple[dict[str, str], str]:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    return headers, created.json()["id"]


async def test_create_list_update_delete_contact(client: AsyncClient) -> None:
    headers, company_id = await _setup_company(client)

    created = await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/contacts",
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com", "title": "CTO"},
        headers=headers,
    )
    assert created.status_code == 201
    contact = created.json()
    assert contact["first_name"] == "Ada"
    assert contact["source"] == "manual"

    listed = await client.get(f"/api/v1/tenants/current/companies/{company_id}/contacts", headers=headers)
    assert len(listed.json()) == 1

    updated = await client.patch(
        f"/api/v1/tenants/current/companies/{company_id}/contacts/{contact['id']}",
        json={"title": "CEO"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "CEO"
    assert updated.json()["first_name"] == "Ada"  # untouched fields survive a partial update

    deleted = await client.delete(
        f"/api/v1/tenants/current/companies/{company_id}/contacts/{contact['id']}", headers=headers
    )
    assert deleted.status_code == 204
    assert (
        await client.get(f"/api/v1/tenants/current/companies/{company_id}/contacts", headers=headers)
    ).json() == []


async def test_viewer_cannot_add_a_contact(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]

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
        f"/api/v1/tenants/current/companies/{company_id}/contacts",
        json={"first_name": "Ada", "last_name": "Lovelace"},
        headers=tenant_headers(client, tenant["slug"]),
    )
    assert response.status_code == 403


async def test_contacts_are_isolated_between_tenants(client: AsyncClient) -> None:
    await signup(client, email="owner-a@example.com")
    tenant_a = (await create_tenant(client, name="Tenant A")).json()
    headers_a = tenant_headers(client, tenant_a["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers_a
    )
    company_id = created.json()["id"]
    await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/contacts",
        json={"first_name": "Ada", "last_name": "Lovelace"},
        headers=headers_a,
    )
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    tenant_b = (await create_tenant(client, name="Tenant B")).json()
    headers_b = tenant_headers(client, tenant_b["slug"])
    # A company id from a tenant B doesn't have — 404 before any contact data could leak.
    response = await client.get(f"/api/v1/tenants/current/companies/{company_id}/contacts", headers=headers_b)
    assert response.status_code == 404
