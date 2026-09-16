"""Scheduled re-profile: diffing a snapshot pair, the worker writing a ProfileChange on a
second run (never a first one), the cron scheduler picking up companies past their plan's
interval, and the changes-feed endpoint surfacing what it found.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.models import Company, Plan, ProfileChange, ProfileStatus, ScrapeJob, Tenant
from app.scraping import pipeline
from app.scraping.extraction import (
    ExtractedCompetency,
    ExtractedEvidence,
    ExtractedOffering,
    ExtractedProfile,
    ExtractionResult,
)
from app.scraping.render import RenderedPage
from app.services.reprofile import ProfileSnapshot, diff_snapshots, enqueue_due_reprofiles
from app.services.scrape_jobs import create_scrape_job
from app.workers.scrape_company import scrape_company
from tests.helpers import create_tenant, signup, tenant_headers


def test_diff_snapshots_is_none_when_nothing_changed() -> None:
    snap = ProfileSnapshot(overview="same", offerings=frozenset({"Widget"}), competencies=frozenset({"Care"}))
    assert diff_snapshots(snap, snap) is None


def test_diff_snapshots_reports_overview_and_added_removed_items() -> None:
    before = ProfileSnapshot(
        overview="Old overview", offerings=frozenset({"Widget"}), competencies=frozenset({"Care"})
    )
    after = ProfileSnapshot(
        overview="New overview", offerings=frozenset({"Gadget"}), competencies=frozenset({"Care", "Speed"})
    )
    diff = diff_snapshots(before, after)
    assert diff == {
        "overview": {"before": "Old overview", "after": "New overview"},
        "offerings": {"added": ["Gadget"], "removed": ["Widget"]},
        "competencies": {"added": ["Speed"], "removed": []},
    }


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)
    monkeypatch.setattr("app.services.reprofile.enqueue_scrape_job", _noop_enqueue)


@pytest.fixture(autouse=True)
def _stub_embed_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]

    monkeypatch.setattr(pipeline, "embed_texts", _fake_embed_texts)


def _extraction_result(*, overview: str, offering_name: str, competency_name: str) -> ExtractionResult:
    return ExtractionResult(
        profile=ExtractedProfile(
            overview=overview,
            offerings=[
                ExtractedOffering(
                    kind="product",
                    name=offering_name,
                    description=f"What {offering_name} is.",
                    category=None,
                    evidence=[ExtractedEvidence(url="https://example.com", quote="evidence")],
                )
            ],
            competencies=[
                ExtractedCompetency(
                    kind="technology",
                    name=competency_name,
                    description=f"How the company has {competency_name}.",
                    evidence=[ExtractedEvidence(url="https://example.com", quote="evidence")],
                )
            ],
        ),
        tokens_in=1000,
        tokens_out=200,
    )


_RENDERED = [
    RenderedPage(
        url="https://example.com",
        final_url="https://example.com",
        status_code=200,
        markdown="# Acme",
        content_hash="abc",
    )
]


async def _run_worker(
    monkeypatch: pytest.MonkeyPatch,
    *,
    job_id: uuid.UUID,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    result: ExtractionResult,
) -> None:
    monkeypatch.setattr(pipeline, "discover_candidate_urls", AsyncMock(return_value=["https://example.com"]))
    monkeypatch.setattr(pipeline, "render_pages", AsyncMock(return_value=_RENDERED))
    monkeypatch.setattr(pipeline, "extract_profile", AsyncMock(return_value=result))
    await scrape_company({}, str(job_id), str(tenant_id), str(company_id))


async def test_first_scrape_writes_no_profile_change(
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

    await set_tenant_scope(db, tenant_id)
    job_id = await db.scalar(select(ScrapeJob.id).where(ScrapeJob.company_id == company_id))
    assert job_id is not None

    await _run_worker(
        monkeypatch,
        job_id=job_id,
        tenant_id=tenant_id,
        company_id=company_id,
        result=_extraction_result(overview="First overview", offering_name="Widget", competency_name="Care"),
    )

    await set_tenant_scope(db, tenant_id)
    stmt = select(ProfileChange).where(ProfileChange.company_id == company_id)
    changes = list((await db.scalars(stmt)).all())
    assert changes == []


async def test_second_scrape_writes_a_profile_change_with_the_diff(
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

    await set_tenant_scope(db, tenant_id)
    first_job_id = await db.scalar(select(ScrapeJob.id).where(ScrapeJob.company_id == company_id))
    assert first_job_id is not None
    await _run_worker(
        monkeypatch,
        job_id=first_job_id,
        tenant_id=tenant_id,
        company_id=company_id,
        result=_extraction_result(overview="First overview", offering_name="Widget", competency_name="Care"),
    )

    await set_tenant_scope(db, tenant_id)
    second_job = await create_scrape_job(db, tenant_id=tenant_id, company_id=company_id)
    await db.commit()
    await set_tenant_scope(db, tenant_id)
    await _run_worker(
        monkeypatch,
        job_id=second_job.id,
        tenant_id=tenant_id,
        company_id=company_id,
        result=_extraction_result(overview="Second overview", offering_name="Gadget", competency_name="Care"),
    )

    await set_tenant_scope(db, tenant_id)
    [change] = list(
        (await db.scalars(select(ProfileChange).where(ProfileChange.company_id == company_id))).all()
    )
    assert change.job_id == second_job.id
    assert change.diff["overview"] == {"before": "First overview", "after": "Second overview"}
    assert change.diff["offerings"] == {"added": ["Gadget"], "removed": ["Widget"]}
    assert "competencies" not in change.diff  # "Care" survived unchanged

    response = await client.get(f"/api/v1/tenants/current/companies/{company_id}/changes", headers=headers)
    assert response.status_code == 200
    [item] = response.json()
    assert item["job_id"] == str(second_job.id)
    assert item["diff"]["offerings"] == {"added": ["Gadget"], "removed": ["Widget"]}


async def test_scheduler_enqueues_only_companies_past_their_plans_interval(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    enqueued: list[uuid.UUID] = []

    async def _record_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id
        enqueued.append(company_id)

    monkeypatch.setattr("app.services.reprofile.enqueue_scrape_job", _record_enqueue)

    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])

    due = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.org"}, headers=headers
    )
    fresh = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.net"}, headers=headers
    )
    due_id = uuid.UUID(due.json()["id"])
    fresh_id = uuid.UUID(fresh.json()["id"])

    await set_tenant_scope(db, tenant_id)
    tenant_row = await db.get(Tenant, tenant_id)
    assert tenant_row is not None
    plan = await db.get(Plan, tenant_row.plan_id)
    assert plan is not None

    due_company = await db.get(Company, due_id)
    fresh_company = await db.get(Company, fresh_id)
    assert due_company is not None and fresh_company is not None
    now = datetime.now(UTC)
    due_company.profile_status = ProfileStatus.DONE
    due_company.last_profiled_at = now - timedelta(days=plan.reprofile_interval_days + 1)
    fresh_company.profile_status = ProfileStatus.DONE
    fresh_company.last_profiled_at = now - timedelta(days=1)
    await db.commit()

    count = await enqueue_due_reprofiles()
    assert count == 1
    assert enqueued == [due_id]

    # enqueue_due_reprofiles ran on its own session — this session's identity map still holds
    # the pre-change objects (expire_on_commit=False), so a fresh read needs an explicit expire.
    db.expire_all()
    await set_tenant_scope(db, tenant_id)
    refreshed_due = await db.get(Company, due_id)
    refreshed_fresh = await db.get(Company, fresh_id)
    assert refreshed_due is not None and refreshed_due.profile_status == ProfileStatus.SCRAPING
    assert refreshed_fresh is not None and refreshed_fresh.profile_status == ProfileStatus.DONE

    # Each company already carries the QUEUED job from its initial POST /companies scrape (never
    # actually run — enqueue is mocked out); a due company gets a second one from the scheduler.
    due_jobs = list((await db.scalars(select(ScrapeJob).where(ScrapeJob.company_id == due_id))).all())
    fresh_jobs = list((await db.scalars(select(ScrapeJob).where(ScrapeJob.company_id == fresh_id))).all())
    assert len(due_jobs) == 2
    assert len(fresh_jobs) == 1
