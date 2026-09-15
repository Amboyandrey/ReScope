"""Tags — create/list/delete at the tenant level, and attach/detach on a company."""

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


async def test_create_list_delete_tag(client: AsyncClient) -> None:
    headers, _company_id = await _setup_company(client)

    created = await client.post(
        "/api/v1/tenants/current/tags", json={"name": "Competitor", "color": "#ff0000"}, headers=headers
    )
    assert created.status_code == 201
    tag = created.json()
    assert tag["name"] == "Competitor"

    listed = await client.get("/api/v1/tenants/current/tags", headers=headers)
    assert [t["name"] for t in listed.json()] == ["Competitor"]

    deleted = await client.delete(f"/api/v1/tenants/current/tags/{tag['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/tenants/current/tags", headers=headers)).json() == []


async def test_duplicate_tag_name_is_rejected(client: AsyncClient) -> None:
    headers, _company_id = await _setup_company(client)
    await client.post("/api/v1/tenants/current/tags", json={"name": "Hot lead"}, headers=headers)
    response = await client.post("/api/v1/tenants/current/tags", json={"name": "Hot lead"}, headers=headers)
    assert response.status_code == 409


async def test_attach_and_detach_tag_on_a_company(client: AsyncClient) -> None:
    headers, company_id = await _setup_company(client)
    tag = (
        await client.post("/api/v1/tenants/current/tags", json={"name": "Hot lead"}, headers=headers)
    ).json()

    attached = await client.put(
        f"/api/v1/tenants/current/companies/{company_id}/tags/{tag['id']}", headers=headers
    )
    assert attached.status_code == 204

    company_tags = await client.get(f"/api/v1/tenants/current/companies/{company_id}/tags", headers=headers)
    assert [t["name"] for t in company_tags.json()] == ["Hot lead"]

    # Attaching again is a no-op, not a conflict.
    reattached = await client.put(
        f"/api/v1/tenants/current/companies/{company_id}/tags/{tag['id']}", headers=headers
    )
    assert reattached.status_code == 204

    detached = await client.delete(
        f"/api/v1/tenants/current/companies/{company_id}/tags/{tag['id']}", headers=headers
    )
    assert detached.status_code == 204
    company_tags = await client.get(f"/api/v1/tenants/current/companies/{company_id}/tags", headers=headers)
    assert company_tags.json() == []

    # Detaching an already-detached tag also succeeds silently.
    again = await client.delete(
        f"/api/v1/tenants/current/companies/{company_id}/tags/{tag['id']}", headers=headers
    )
    assert again.status_code == 204


async def test_tags_are_isolated_between_tenants(client: AsyncClient) -> None:
    headers_a, _company_id_a = await _setup_company(client)
    await client.post("/api/v1/tenants/current/tags", json={"name": "Only in A"}, headers=headers_a)
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    tenant_b = (await create_tenant(client, name="Tenant B")).json()
    headers_b = tenant_headers(client, tenant_b["slug"])
    assert (await client.get("/api/v1/tenants/current/tags", headers=headers_b)).json() == []
