"""The search and similar-companies HTTP endpoints — permissions and the response shape; the
ranking logic itself is covered in tests/test_search.py against the service directly."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.models import Embedding, SourceKind
from app.services import search as search_module
from tests.helpers import create_tenant, signup, tenant_headers

_DIMENSIONS = 1024


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def test_search_requires_at_least_viewer(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(search_module, "embed_text", AsyncMock(return_value=[0.0] * _DIMENSIONS))
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    response = await client.get("/api/v1/tenants/current/search", params={"q": "widgets"}, headers=headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_search_returns_hits_with_evidence_shape(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])

    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = uuid.UUID(created.json()["id"])

    vector = [1.0] + [0.0] * (_DIMENSIONS - 1)
    await set_tenant_scope(db, tenant_id)
    db.add(
        Embedding(
            tenant_id=tenant_id,
            company_id=company_id,
            source_kind=SourceKind.OFFERING,
            source_id=uuid.uuid4(),
            content="widget forging",
            embedding=vector,
            model="test",
        )
    )
    await db.commit()

    monkeypatch.setattr(search_module, "embed_text", AsyncMock(return_value=vector))

    response = await client.get("/api/v1/tenants/current/search", params={"q": "widgets"}, headers=headers)
    assert response.status_code == 200
    [hit] = response.json()
    assert hit["company"]["id"] == str(company_id)
    assert hit["source_kind"] == "offering"
    assert hit["content"] == "widget forging"


async def test_similar_404s_for_a_company_in_another_tenant(client: AsyncClient) -> None:
    await signup(client, email="owner-a@example.com")
    tenant_a = (await create_tenant(client, name="Tenant A")).json()
    headers_a = tenant_headers(client, tenant_a["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers_a
    )
    company_id = created.json()["id"]
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    tenant_b = (await create_tenant(client, name="Tenant B")).json()
    response = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/similar",
        headers=tenant_headers(client, tenant_b["slug"]),
    )
    assert response.status_code == 404
