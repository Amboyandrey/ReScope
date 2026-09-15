"""The usage ledger — recording events and counting/summing them for the current month."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.models import ScrapeJob, UsageKind
from app.services.usage import count_this_month, record_usage_event, sum_cost_this_month
from tests.helpers import create_tenant, signup, tenant_headers


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def _setup_job(client: AsyncClient, db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Sign up, create a tenant and a company (and its first job), return (tenant_id, job_id)."""
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = uuid.UUID(created.json()["id"])
    await set_tenant_scope(db, tenant_id)
    job_id = await db.scalar(select(ScrapeJob.id).where(ScrapeJob.company_id == company_id))
    assert job_id is not None
    return tenant_id, job_id


async def test_count_this_month_only_counts_the_given_kind(client: AsyncClient, db: AsyncSession) -> None:
    tenant_id, job_id = await _setup_job(client, db)
    await record_usage_event(
        db,
        tenant_id=tenant_id,
        job_id=job_id,
        kind=UsageKind.PROFILE,
        model="claude-sonnet-5",
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.001,
    )
    await record_usage_event(
        db,
        tenant_id=tenant_id,
        job_id=job_id,
        kind=UsageKind.DEEP_PROFILE,
        model="claude-opus-5",
        tokens_in=200,
        tokens_out=80,
        cost_usd=0.01,
    )
    await db.commit()
    await set_tenant_scope(db, tenant_id)

    assert await count_this_month(db, tenant_id=tenant_id, kind=UsageKind.PROFILE) == 1
    assert await count_this_month(db, tenant_id=tenant_id, kind=UsageKind.DEEP_PROFILE) == 1


async def test_sum_cost_this_month_adds_across_kinds(client: AsyncClient, db: AsyncSession) -> None:
    tenant_id, job_id = await _setup_job(client, db)
    await record_usage_event(
        db,
        tenant_id=tenant_id,
        job_id=job_id,
        kind=UsageKind.PROFILE,
        model="claude-sonnet-5",
        tokens_in=100,
        tokens_out=50,
        cost_usd=1.5,
    )
    await record_usage_event(
        db,
        tenant_id=tenant_id,
        job_id=job_id,
        kind=UsageKind.DEEP_PROFILE,
        model="claude-opus-5",
        tokens_in=200,
        tokens_out=80,
        cost_usd=2.5,
    )
    await db.commit()
    await set_tenant_scope(db, tenant_id)

    assert await sum_cost_this_month(db, tenant_id=tenant_id) == pytest.approx(4.0)


async def test_sum_cost_is_zero_with_no_events(client: AsyncClient, db: AsyncSession) -> None:
    tenant_id, _ = await _setup_job(client, db)
    await set_tenant_scope(db, tenant_id)
    assert await sum_cost_this_month(db, tenant_id=tenant_id) == 0
