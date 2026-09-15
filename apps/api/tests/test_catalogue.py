"""The catalogue: filtering a tenant's companies by fact, competency kind, and tag, the facets
that drive those filters, and how a semantic query narrows and ranks the result.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.models import Company, CompanyType, Competency, CompetencyKind, Embedding, SourceKind
from app.services import search as search_module
from app.services.catalogue import CatalogueFilters, list_catalogue
from app.services.tags import attach_tag, create_tag
from tests.helpers import create_tenant, signup, tenant_headers

_DIMENSIONS = 1024


def _vector(hot_index: int) -> list[float]:
    v = [0.0] * _DIMENSIONS
    v[hot_index] = 1.0
    return v


def _partial_vector(primary_index: int, secondary_index: int, primary_weight: float) -> list[float]:
    """A vector mostly (but not entirely) aligned with `primary_index` — cosine distance from the
    pure `_vector(primary_index)` is small but nonzero, unlike two orthogonal one-hot vectors."""
    v = [0.0] * _DIMENSIONS
    v[primary_index] = primary_weight
    v[secondary_index] = (1 - primary_weight**2) ** 0.5
    return v


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


_CataloguePools = tuple[dict[str, str], uuid.UUID, dict[str, uuid.UUID]]


async def _setup(client: AsyncClient, db: AsyncSession) -> _CataloguePools:
    """Three companies: a German manufacturer with a technology competency and a tag, a US
    software company with a certification competency, and a bare company with no facts at all."""
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])

    url = "/api/v1/tenants/current/companies"
    de = await client.post(url, json={"domain": "example.com"}, headers=headers)
    us = await client.post(url, json={"domain": "example.org"}, headers=headers)
    bare = await client.post(url, json={"domain": "example.net"}, headers=headers)
    de_id, us_id, bare_id = (uuid.UUID(r.json()["id"]) for r in (de, us, bare))

    await set_tenant_scope(db, tenant_id)
    de_company = await db.get(Company, de_id)
    us_company = await db.get(Company, us_id)
    assert de_company is not None and us_company is not None
    de_company.hq_country = "DE"
    de_company.company_type = CompanyType.MANUFACTURER
    de_company.industry = "Robotics"
    us_company.hq_country = "US"
    us_company.company_type = CompanyType.SOFTWARE
    us_company.industry = "SaaS"

    db.add(
        Competency(
            tenant_id=tenant_id,
            company_id=de_id,
            kind=CompetencyKind.TECHNOLOGY,
            name="Computer vision",
            description="In-house model for bin-picking.",
        )
    )
    db.add(
        Competency(
            tenant_id=tenant_id,
            company_id=us_id,
            kind=CompetencyKind.CERTIFICATION,
            name="SOC 2",
            description="Independently audited SOC 2 Type II.",
        )
    )
    tag = await create_tag(db, tenant_id=tenant_id, name="Robotics", color="#2563eb")
    await attach_tag(db, tenant_id=tenant_id, company_id=de_id, tag_id=tag.id)
    await db.commit()

    return headers, tenant_id, {"de": de_id, "us": us_id, "bare": bare_id, "tag": tag.id}


async def test_no_filters_lists_every_company(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, ids = await _setup(client, db)
    response = await client.get("/api/v1/tenants/current/catalogue", headers=headers)
    assert response.status_code == 200
    assert {c["id"] for c in response.json()} == set(str(v) for v in (ids["de"], ids["us"], ids["bare"]))


async def test_filter_by_country(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, ids = await _setup(client, db)
    response = await client.get(
        "/api/v1/tenants/current/catalogue", params={"country": "de"}, headers=headers
    )
    assert [c["id"] for c in response.json()] == [str(ids["de"])]


async def test_filter_by_company_type(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, ids = await _setup(client, db)
    response = await client.get(
        "/api/v1/tenants/current/catalogue", params={"company_type": "software"}, headers=headers
    )
    assert [c["id"] for c in response.json()] == [str(ids["us"])]


async def test_filter_by_industry(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, ids = await _setup(client, db)
    response = await client.get(
        "/api/v1/tenants/current/catalogue", params={"industry": "Robotics"}, headers=headers
    )
    assert [c["id"] for c in response.json()] == [str(ids["de"])]


async def test_filter_by_competency_kind(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, ids = await _setup(client, db)
    response = await client.get(
        "/api/v1/tenants/current/catalogue", params={"competency_kind": "certification"}, headers=headers
    )
    assert [c["id"] for c in response.json()] == [str(ids["us"])]


async def test_filter_by_tag(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, ids = await _setup(client, db)
    response = await client.get(
        "/api/v1/tenants/current/catalogue", params={"tag": str(ids["tag"])}, headers=headers
    )
    assert [c["id"] for c in response.json()] == [str(ids["de"])]


async def test_combining_filters_is_an_and(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, _ids = await _setup(client, db)
    response = await client.get(
        "/api/v1/tenants/current/catalogue",
        params={"country": "DE", "company_type": "software"},
        headers=headers,
    )
    assert response.json() == []


async def test_catalogue_entries_include_offerings_and_competencies(
    client: AsyncClient, db: AsyncSession
) -> None:
    headers, _tenant_id, ids = await _setup(client, db)
    response = await client.get(
        "/api/v1/tenants/current/catalogue", params={"country": "DE"}, headers=headers
    )
    [entry] = response.json()
    assert entry["id"] == str(ids["de"])
    assert [c["name"] for c in entry["competencies"]] == ["Computer vision"]


async def test_facets_report_distinct_values_and_counts(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, _ids = await _setup(client, db)
    response = await client.get("/api/v1/tenants/current/catalogue/facets", headers=headers)
    assert response.status_code == 200
    facets = response.json()
    assert {f["value"]: f["count"] for f in facets["countries"]} == {"DE": 1, "US": 1}
    assert {f["value"]: f["count"] for f in facets["company_types"]} == {
        "manufacturer": 1,
        "software": 1,
    }
    assert {f["value"]: f["count"] for f in facets["competency_kinds"]} == {
        "technology": 1,
        "certification": 1,
    }
    assert [(t["name"], t["count"]) for t in facets["tags"]] == [("Robotics", 1)]


async def test_semantic_query_ranks_and_can_combine_with_a_filter(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, tenant_id, ids = await _setup(client, db)
    await set_tenant_scope(db, tenant_id)  # transaction-local — reset after _setup's own commit

    db.add(
        Embedding(
            tenant_id=tenant_id,
            company_id=ids["de"],
            source_kind=SourceKind.COMPANY_SUMMARY,
            source_id=ids["de"],
            content="German manufacturer",
            embedding=_vector(0),
            model="test",
        )
    )
    db.add(
        Embedding(
            tenant_id=tenant_id,
            company_id=ids["us"],
            source_kind=SourceKind.COMPANY_SUMMARY,
            source_id=ids["us"],
            content="US software company",
            embedding=_vector(1),
            model="test",
        )
    )
    await db.commit()

    monkeypatch.setattr(search_module, "embed_text", AsyncMock(return_value=_vector(0)))
    response = await client.get(
        "/api/v1/tenants/current/catalogue", params={"q": "robotics"}, headers=headers
    )
    assert [c["id"] for c in response.json()] == [str(ids["de"])]

    # Combined with a filter that excludes the semantic match: no results, not a fallback to it.
    response = await client.get(
        "/api/v1/tenants/current/catalogue",
        params={"q": "robotics", "company_type": "software"},
        headers=headers,
    )
    assert response.json() == []


async def test_catalogue_is_scoped_to_the_tenant(client: AsyncClient, db: AsyncSession) -> None:
    await _setup(client, db)
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    tenant_b = (await create_tenant(client, name="Tenant B")).json()
    headers_b = tenant_headers(client, tenant_b["slug"])
    response = await client.get("/api/v1/tenants/current/catalogue", headers=headers_b)
    assert response.json() == []


async def test_list_catalogue_service_orders_semantic_results_by_relevance(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, tenant_id, ids = await _setup(client, db)
    del headers
    await set_tenant_scope(db, tenant_id)  # transaction-local — reset after _setup's own commit

    db.add(
        Embedding(
            tenant_id=tenant_id,
            company_id=ids["us"],
            source_kind=SourceKind.COMPANY_SUMMARY,
            source_id=ids["us"],
            content="close match",
            embedding=_vector(0),
            model="test",
        )
    )
    db.add(
        Embedding(
            tenant_id=tenant_id,
            company_id=ids["de"],
            source_kind=SourceKind.COMPANY_SUMMARY,
            source_id=ids["de"],
            content="far match",
            embedding=_partial_vector(0, 1, 0.9),
            model="test",
        )
    )
    await db.commit()
    await set_tenant_scope(db, tenant_id)

    monkeypatch.setattr(search_module, "embed_text", AsyncMock(return_value=_vector(0)))
    results = await list_catalogue(db, tenant_id=tenant_id, filters=CatalogueFilters(q="anything"))
    assert [c.id for c in results] == [ids["us"], ids["de"]]
