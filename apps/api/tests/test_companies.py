"""Adding, listing, viewing, and deleting companies — plus the SSRF guard on the domain field.

Scraping itself is stubbed out (a no-op): these tests are about the API surface, not the worker
or the pipeline — see test_discovery.py, test_extraction.py, and (once it exists) a dedicated
pipeline test for that.
"""

import uuid

import pytest
from httpx import AsyncClient

from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


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
    assert body["profile_status"] == "scraping"


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


async def test_scrape_jobs_are_listed_for_the_company(client: AsyncClient) -> None:
    headers = await _setup_tenant(client)
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]

    jobs = await client.get(f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs", headers=headers)
    assert jobs.status_code == 200
    [job] = jobs.json()
    assert job["status"] == "queued"
    assert job["mode"] == "fast"


async def test_scrape_jobs_404_for_a_company_in_another_tenant(client: AsyncClient) -> None:
    headers_a = await _setup_tenant(client, email="owner-a@example.com", tenant_name="Tenant A")
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers_a
    )
    company_id = created.json()["id"]
    client.cookies.clear()

    headers_b = await _setup_tenant(client, email="owner-b@example.com", tenant_name="Tenant B")
    response = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs", headers=headers_b
    )
    assert response.status_code == 404


async def test_reprofile_queues_a_second_scrape_job(client: AsyncClient) -> None:
    headers = await _setup_tenant(client)
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]

    response = await client.post(f"/api/v1/tenants/current/companies/{company_id}/reprofile", headers=headers)
    assert response.status_code == 200
    assert response.json()["profile_status"] == "scraping"

    jobs = await client.get(f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs", headers=headers)
    assert len(jobs.json()) == 2


async def test_viewer_cannot_reprofile(client: AsyncClient) -> None:
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
        f"/api/v1/tenants/current/companies/{company_id}/reprofile",
        headers=tenant_headers(client, tenant["slug"]),
    )
    assert response.status_code == 403


async def test_reprofile_404s_for_a_company_in_another_tenant(client: AsyncClient) -> None:
    headers_a = await _setup_tenant(client, email="owner-a@example.com", tenant_name="Tenant A")
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers_a
    )
    company_id = created.json()["id"]
    client.cookies.clear()

    headers_b = await _setup_tenant(client, email="owner-b@example.com", tenant_name="Tenant B")
    response = await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/reprofile", headers=headers_b
    )
    assert response.status_code == 404
