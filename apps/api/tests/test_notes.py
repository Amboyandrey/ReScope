"""A company's notes — create, list, delete, and tenant isolation."""

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers import create_tenant, signup, tenant_headers


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


async def test_create_list_delete_note(client: AsyncClient) -> None:
    headers, company_id = await _setup_company(client)

    created = await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/notes",
        json={"body": "Talked to their VP of sales, follow up next week."},
        headers=headers,
    )
    assert created.status_code == 201
    note = created.json()
    assert note["body"].startswith("Talked to their VP")

    listed = await client.get(f"/api/v1/tenants/current/companies/{company_id}/notes", headers=headers)
    assert len(listed.json()) == 1

    deleted = await client.delete(
        f"/api/v1/tenants/current/companies/{company_id}/notes/{note['id']}", headers=headers
    )
    assert deleted.status_code == 204
    assert (
        await client.get(f"/api/v1/tenants/current/companies/{company_id}/notes", headers=headers)
    ).json() == []


async def test_notes_are_newest_first(client: AsyncClient) -> None:
    headers, company_id = await _setup_company(client)
    await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/notes", json={"body": "first"}, headers=headers
    )
    await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/notes", json={"body": "second"}, headers=headers
    )
    listed = await client.get(f"/api/v1/tenants/current/companies/{company_id}/notes", headers=headers)
    assert [n["body"] for n in listed.json()] == ["second", "first"]


async def test_notes_are_isolated_between_tenants(client: AsyncClient) -> None:
    headers_a, company_id = await _setup_company(client)
    await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/notes", json={"body": "secret"}, headers=headers_a
    )
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    tenant_b = (await create_tenant(client, name="Tenant B")).json()
    headers_b = tenant_headers(client, tenant_b["slug"])
    response = await client.get(f"/api/v1/tenants/current/companies/{company_id}/notes", headers=headers_b)
    assert response.status_code == 404
