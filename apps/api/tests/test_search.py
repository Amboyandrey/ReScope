"""Semantic search and similar companies — real pgvector cosine ordering, a mocked query
embedding (these tests check the SQL and tenant scoping, not the embedding model itself)."""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.models import Embedding, SourceKind
from app.services import search as search_module
from app.services.search import semantic_search, similar_companies
from tests.helpers import create_tenant, signup, tenant_headers

_DIMENSIONS = 1024


def _vector(hot_index: int, value: float = 1.0) -> list[float]:
    """A mostly-zero vector with one dimension set — cosine distance between two of these is easy
    to reason about, unlike random floats: identical hot index and sign means distance 0."""
    v = [0.0] * _DIMENSIONS
    v[hot_index] = value
    return v


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def _create_company(client: AsyncClient, headers: dict[str, str], domain: str) -> uuid.UUID:
    created = await client.post("/api/v1/tenants/current/companies", json={"domain": domain}, headers=headers)
    assert created.status_code == 201
    return uuid.UUID(created.json()["id"])


async def _add_embedding(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    source_kind: SourceKind,
    source_id: uuid.UUID,
    content: str,
    vector: list[float],
) -> None:
    db.add(
        Embedding(
            tenant_id=tenant_id,
            company_id=company_id,
            source_kind=source_kind,
            source_id=source_id,
            content=content,
            embedding=vector,
            model="test",
        )
    )
    await db.flush()


async def test_semantic_search_orders_by_distance_and_dedupes_per_company(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])

    close_id = await _create_company(client, headers, "example.com")
    far_id = await _create_company(client, headers, "example.org")

    await set_tenant_scope(db, tenant_id)
    # Two rows for `close`: search should return the company once, at its best (closest) match.
    await _add_embedding(
        db,
        tenant_id=tenant_id,
        company_id=close_id,
        source_kind=SourceKind.OFFERING,
        source_id=uuid.uuid4(),
        content="widget forging",
        vector=_vector(0, 1.0),
    )
    await _add_embedding(
        db,
        tenant_id=tenant_id,
        company_id=close_id,
        source_kind=SourceKind.COMPETENCY,
        source_id=uuid.uuid4(),
        content="unrelated capability",
        vector=_vector(500, 1.0),
    )
    await _add_embedding(
        db,
        tenant_id=tenant_id,
        company_id=far_id,
        source_kind=SourceKind.OFFERING,
        source_id=uuid.uuid4(),
        content="something else entirely",
        vector=_vector(0, -1.0),  # opposite direction — cosine distance 2, filtered out
    )
    await db.commit()
    await set_tenant_scope(db, tenant_id)  # transaction-local — reset after the commit above

    monkeypatch.setattr(search_module, "embed_text", AsyncMock(return_value=_vector(0, 1.0)))

    hits = await semantic_search(db, tenant_id=tenant_id, query="widgets")

    assert len(hits) == 1
    assert hits[0].company.id == close_id
    assert hits[0].content == "widget forging"
    assert hits[0].distance == pytest.approx(0.0, abs=1e-4)


async def test_semantic_search_is_scoped_to_the_tenant(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(client, email="owner-a@example.com")
    tenant_a = (await create_tenant(client, name="Tenant A")).json()
    tenant_a_id = uuid.UUID(tenant_a["id"])
    headers_a = tenant_headers(client, tenant_a["slug"])
    company_a = await _create_company(client, headers_a, "example.com")

    await set_tenant_scope(db, tenant_a_id)
    await _add_embedding(
        db,
        tenant_id=tenant_a_id,
        company_id=company_a,
        source_kind=SourceKind.OFFERING,
        source_id=uuid.uuid4(),
        content="acme widgets",
        vector=_vector(0, 1.0),
    )
    await db.commit()
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    tenant_b = (await create_tenant(client, name="Tenant B")).json()
    tenant_b_id = uuid.UUID(tenant_b["id"])

    monkeypatch.setattr(search_module, "embed_text", AsyncMock(return_value=_vector(0, 1.0)))
    hits = await semantic_search(db, tenant_id=tenant_b_id, query="widgets")
    assert hits == []


async def test_similar_companies_excludes_self_and_ranks_by_distance(
    client: AsyncClient, db: AsyncSession
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])

    target = await _create_company(client, headers, "example.com")
    close = await _create_company(client, headers, "example.net")
    far = await _create_company(client, headers, "example.org")

    await set_tenant_scope(db, tenant_id)
    for company_id, vector in [
        (target, _vector(0, 1.0)),
        (close, _vector(0, 0.99)),
        (far, _vector(1, 1.0)),
    ]:
        await _add_embedding(
            db,
            tenant_id=tenant_id,
            company_id=company_id,
            source_kind=SourceKind.COMPANY_SUMMARY,
            source_id=company_id,
            content="summary",
            vector=vector,
        )
    await db.commit()
    await set_tenant_scope(db, tenant_id)  # transaction-local — reset after the commit above

    results = await similar_companies(db, tenant_id=tenant_id, company_id=target)

    assert [c.id for c, _ in results] == [close, far]
    assert all(c.id != target for c, _ in results)


async def test_similar_companies_returns_nothing_without_a_summary_embedding(
    client: AsyncClient, db: AsyncSession
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])
    company_id = await _create_company(client, headers, "example.com")

    await set_tenant_scope(db, tenant_id)
    assert await similar_companies(db, tenant_id=tenant_id, company_id=company_id) == []
