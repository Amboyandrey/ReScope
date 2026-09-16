"""Plan quotas and the platform-wide scraping killswitch — both checked before a company is
even created, so a rejected request never leaves an orphaned row behind."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.errors import QuotaExceeded
from app.models import ScrapeMode, Tenant, UsageKind
from app.services.platform_settings import set_scraping_paused
from app.services.quotas import assert_within_quota
from app.services.usage import record_usage_event
from tests.helpers import create_tenant, signup, tenant_headers


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def test_free_plan_allows_a_profile_under_the_limit(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)
    tenant_row = await db.get(Tenant, tenant_id)
    assert tenant_row is not None
    await assert_within_quota(db, tenant=tenant_row, mode=ScrapeMode.FAST)  # does not raise


async def test_company_creation_is_rejected_once_the_monthly_profile_quota_is_used_up(
    client: AsyncClient, db: AsyncSession
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])

    # Free plan is seeded with profiles_per_month=10 (migration 0002) — fill it with fake usage
    # rather than actually creating and profiling 10 companies.
    first = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = first.json()["id"]
    jobs_resp = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs", headers=headers
    )
    job_id = uuid.UUID(jobs_resp.json()[0]["id"])
    await set_tenant_scope(db, tenant_id)
    for _ in range(10):
        await record_usage_event(
            db,
            tenant_id=tenant_id,
            job_id=job_id,
            kind=UsageKind.PROFILE,
            model="claude-sonnet-5",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.01,
        )
    await db.commit()

    response = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.org"}, headers=headers
    )
    assert response.status_code == 402


async def test_deep_quota_is_tracked_separately_from_fast(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])

    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]
    jobs_resp = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs", headers=headers
    )
    job_id = uuid.UUID(jobs_resp.json()[0]["id"])
    # Free plan's deep_runs_per_month is 2 — two DEEP_PROFILE events use it up.
    await set_tenant_scope(db, tenant_id)
    for _ in range(2):
        await record_usage_event(
            db,
            tenant_id=tenant_id,
            job_id=job_id,
            kind=UsageKind.DEEP_PROFILE,
            model="claude-opus-5",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.05,
        )
    await db.commit()

    # A fast-mode company is still allowed — deep and fast quotas don't share a counter.
    fast = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.org", "mode": "fast"}, headers=headers
    )
    assert fast.status_code == 201

    deep = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.net", "mode": "deep"}, headers=headers
    )
    assert deep.status_code == 402


async def test_deep_quota_is_shared_across_both_tier_2_providers(
    client: AsyncClient, db: AsyncSession
) -> None:
    """A custom-agent DEEP_PROFILE run and a Browser Use Cloud BROWSER_USE_RUN both count against
    the same `deep_runs_per_month` ceiling — a tenant can't double it by splitting across the two.
    Also guards against `count_this_month`'s `UsageKind | Sequence[UsageKind]` overload treating a
    single `UsageKind` (itself a `str`, and so a `Sequence[str]`) as a sequence of characters."""
    await signup(client)
    tenant_data = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant_data["id"])
    headers = tenant_headers(client, tenant_data["slug"])

    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]
    jobs_resp = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs", headers=headers
    )
    job_id = uuid.UUID(jobs_resp.json()[0]["id"])

    await set_tenant_scope(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None
    # Free plan's deep_runs_per_month is 2 — one of each kind uses it up.
    await record_usage_event(
        db,
        tenant_id=tenant_id,
        job_id=job_id,
        kind=UsageKind.DEEP_PROFILE,
        model="claude-opus-5",
        tokens_in=100,
        tokens_out=50,
        cost_usd=0.05,
    )
    await record_usage_event(
        db,
        tenant_id=tenant_id,
        job_id=job_id,
        kind=UsageKind.BROWSER_USE_RUN,
        model="browser-use-llm",
        tokens_in=0,
        tokens_out=0,
        cost_usd=0.04,
    )
    await db.commit()
    await set_tenant_scope(db, tenant_id)

    with pytest.raises(QuotaExceeded):
        await assert_within_quota(db, tenant=tenant, mode=ScrapeMode.DEEP)

    # A single fast-mode run is still counted only against `profiles_per_month`, unaffected by
    # the now-exhausted deep ceiling — confirms the single-kind branch wasn't broken along the way.
    await assert_within_quota(db, tenant=tenant, mode=ScrapeMode.FAST)


async def test_company_creation_is_rejected_while_scraping_is_paused(
    client: AsyncClient, db: AsyncSession
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    await set_scraping_paused(db, paused=True)
    await db.commit()

    response = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    assert response.status_code == 503

    await set_scraping_paused(db, paused=False)
    await db.commit()
    response = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    assert response.status_code == 201
