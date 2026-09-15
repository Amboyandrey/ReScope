"""The scrape pipeline end to end at the service layer — discovery, render, and extraction are
each mocked (they have their own dedicated tests), so this is purely about the orchestration:
does a successful run write the right rows, and does a failure leave the company in FAILED.

Embedding calls are mocked too rather than left to hit a real (or absent) TEI service: without
the mock, a developer running these tests with `docker compose up embeddings` locally gets silent,
real network calls that pass by accident, while CI (no embeddings service in its job) gets the
pipeline's own graceful-degradation path instead — neither actually exercises the embedding step.
"""

import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.models import (
    Company,
    Competency,
    Embedding,
    Offering,
    ProfileStatus,
    ScrapeJob,
    ScrapePage,
    ScrapeStatus,
    SourceKind,
    UsageEvent,
    UsageKind,
)
from app.models.embedding import EMBEDDING_DIMENSIONS
from app.scraping import pipeline
from app.scraping.extraction import (
    ExtractedCompetency,
    ExtractedEvidence,
    ExtractedOffering,
    ExtractedProfile,
    ExtractionResult,
)
from app.scraping.render import RenderedPage
from tests.helpers import create_tenant, tenant_headers


def _fake_vector(seed: float) -> list[float]:
    return [seed] * EMBEDDING_DIMENSIONS


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


@pytest.fixture(autouse=True)
def _stub_embed_texts(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_embed_texts(texts: list[str]) -> list[list[float]]:
        return [_fake_vector(float(i)) for i in range(len(texts))]

    monkeypatch.setattr(pipeline, "embed_texts", _fake_embed_texts)


async def _create_company(
    client: AsyncClient, db: AsyncSession, *, mode: str = "fast"
) -> tuple[Company, ScrapeJob]:
    from tests.helpers import signup

    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies",
        json={"domain": "example.com", "mode": mode},
        headers=headers,
    )
    company_id = uuid.UUID(created.json()["id"])
    tenant_id = uuid.UUID(tenant["id"])

    await set_tenant_scope(db, tenant_id)
    company = await db.get(Company, company_id)
    job = await db.scalar(select(ScrapeJob).where(ScrapeJob.company_id == company_id))
    assert company is not None and job is not None
    return company, job


async def test_successful_run_writes_profile_and_marks_done(client: AsyncClient, db: AsyncSession) -> None:
    company, job = await _create_company(client, db)

    fake_result = ExtractionResult(
        profile=ExtractedProfile(
            overview="Acme makes example widgets.",
            offerings=[
                ExtractedOffering(
                    kind="product",
                    name="Widget",
                    description=None,
                    category=None,
                    evidence=[ExtractedEvidence(url="https://example.com", quote="We make widgets")],
                )
            ],
            competencies=[
                ExtractedCompetency(
                    kind="technology",
                    name="Widget-forging",
                    description=None,
                    evidence=[ExtractedEvidence(url="https://example.com", quote="forged with care")],
                )
            ],
        ),
        tokens_in=1000,
        tokens_out=200,
    )
    rendered = [
        RenderedPage(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            markdown="# Acme\n\nWe make widgets",
            content_hash="abc",
        )
    ]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "discover_candidate_urls", AsyncMock(return_value=["https://example.com"]))
        mp.setattr(pipeline, "render_pages", AsyncMock(return_value=rendered))
        mp.setattr(pipeline, "extract_profile", AsyncMock(return_value=fake_result))
        await pipeline.run_scrape_job(db, job=job, company=company)
        await db.commit()

    await set_tenant_scope(db, company.tenant_id)
    refreshed = await db.get(Company, company.id)
    assert refreshed is not None
    assert refreshed.profile_status == ProfileStatus.DONE
    assert refreshed.overview == "Acme makes example widgets."

    offerings = list((await db.scalars(select(Offering).where(Offering.company_id == company.id))).all())
    competencies = list(
        (await db.scalars(select(Competency).where(Competency.company_id == company.id))).all()
    )
    assert [o.name for o in offerings] == ["Widget"]
    assert offerings[0].evidence == [{"url": "https://example.com", "quote": "We make widgets"}]
    assert [c.name for c in competencies] == ["Widget-forging"]

    embeddings = list((await db.scalars(select(Embedding).where(Embedding.company_id == company.id))).all())
    by_kind = {e.source_kind: e for e in embeddings}
    assert set(by_kind) == {SourceKind.COMPANY_SUMMARY, SourceKind.OFFERING, SourceKind.COMPETENCY}
    assert by_kind[SourceKind.COMPANY_SUMMARY].source_id == company.id
    assert by_kind[SourceKind.OFFERING].source_id == offerings[0].id
    assert by_kind[SourceKind.OFFERING].content == "Widget"
    assert by_kind[SourceKind.COMPETENCY].source_id == competencies[0].id
    assert len(by_kind[SourceKind.COMPANY_SUMMARY].embedding) == EMBEDDING_DIMENSIONS

    refreshed_job = await db.get(ScrapeJob, job.id)
    assert refreshed_job is not None
    assert refreshed_job.status == ScrapeStatus.DONE
    assert refreshed_job.tier_reached == 1
    assert refreshed_job.pages_fetched == 1
    assert refreshed_job.tokens_in == 1000
    assert float(refreshed_job.cost_usd) > 0


async def test_no_candidate_pages_completes_the_job_with_nothing_extracted(
    client: AsyncClient, db: AsyncSession
) -> None:
    company, job = await _create_company(client, db)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "discover_candidate_urls", AsyncMock(return_value=[]))
        await pipeline.run_scrape_job(db, job=job, company=company)
        await db.commit()

    await set_tenant_scope(db, company.tenant_id)
    refreshed = await db.get(Company, company.id)
    assert refreshed is not None
    assert refreshed.profile_status == ProfileStatus.DONE
    assert refreshed.overview is None


async def test_worker_marks_job_and_company_failed_on_exception(
    client: AsyncClient, db: AsyncSession
) -> None:
    from app.workers.scrape_company import scrape_company

    company, job = await _create_company(client, db)
    await db.commit()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.scraping.pipeline.discover_candidate_urls",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        await scrape_company({}, str(job.id), str(company.tenant_id), str(company.id))

    # populate_existing: `scrape_company` ran in its own session and committed there — this
    # session's identity map still holds the pre-failure objects unless told to re-fetch.
    await set_tenant_scope(db, company.tenant_id)
    refreshed_company = await db.get(Company, company.id, populate_existing=True)
    refreshed_job = await db.get(ScrapeJob, job.id, populate_existing=True)
    assert refreshed_company is not None and refreshed_job is not None
    assert refreshed_company.profile_status == ProfileStatus.FAILED
    assert refreshed_job.status == ScrapeStatus.FAILED
    assert refreshed_job.error is not None and "boom" in refreshed_job.error


async def test_embedding_failure_does_not_fail_the_job(client: AsyncClient, db: AsyncSession) -> None:
    """A down or slow embeddings service degrades the company to searchable-later, not FAILED."""
    company, job = await _create_company(client, db)

    fake_result = ExtractionResult(
        profile=ExtractedProfile(
            overview="Acme makes example widgets.",
            offerings=[
                ExtractedOffering(
                    kind="product",
                    name="Widget",
                    description=None,
                    category=None,
                    evidence=[ExtractedEvidence(url="https://example.com", quote="We make widgets")],
                )
            ],
            competencies=[],
        ),
        tokens_in=10,
        tokens_out=5,
    )
    rendered = [
        RenderedPage(
            url="https://example.com",
            final_url="https://example.com",
            status_code=200,
            markdown="# Acme",
            content_hash="abc",
        )
    ]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "discover_candidate_urls", AsyncMock(return_value=["https://example.com"]))
        mp.setattr(pipeline, "render_pages", AsyncMock(return_value=rendered))
        mp.setattr(pipeline, "extract_profile", AsyncMock(return_value=fake_result))
        mp.setattr(pipeline, "embed_texts", AsyncMock(side_effect=ConnectionError("embeddings down")))
        await pipeline.run_scrape_job(db, job=job, company=company)
        await db.commit()

    await set_tenant_scope(db, company.tenant_id)
    refreshed = await db.get(Company, company.id)
    assert refreshed is not None
    assert refreshed.profile_status == ProfileStatus.DONE  # extraction still succeeded
    assert refreshed.overview == "Acme makes example widgets."

    embeddings = list((await db.scalars(select(Embedding).where(Embedding.company_id == company.id))).all())
    assert embeddings == []


async def test_deep_mode_runs_tier_2_and_records_a_separate_usage_event(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A deep-mode job explores visually in addition to Tier 1, reaches tier_reached=2, stores
    the exploration's screenshot, and bills it as its own DEEP_PROFILE event — separate from the
    PROFILE event the extraction call itself still generates."""
    from app.core import storage as storage_module
    from app.scraping.visual_agent import ExplorationResult

    monkeypatch.setattr(storage_module.settings, "storage_dir", str(tmp_path))
    company, job = await _create_company(client, db, mode="deep")

    fake_result = ExtractionResult(
        profile=ExtractedProfile(overview="Acme.", offerings=[], competencies=[]),
        tokens_in=10,
        tokens_out=5,
    )
    visual_page = RenderedPage(
        url="https://example.com",
        final_url="https://example.com/tab-2",
        status_code=None,
        markdown="# Revealed content",
        content_hash="deadbeef",
        screenshot=b"fake-png-bytes",
    )
    exploration = ExplorationResult(pages=[visual_page], tokens_in=300, tokens_out=60)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(pipeline, "discover_candidate_urls", AsyncMock(return_value=[]))
        mp.setattr(pipeline, "explore_visually", AsyncMock(return_value=exploration))
        mp.setattr(pipeline, "extract_profile", AsyncMock(return_value=fake_result))
        await pipeline.run_scrape_job(db, job=job, company=company)
        await db.commit()

    await set_tenant_scope(db, company.tenant_id)
    refreshed_job = await db.get(ScrapeJob, job.id)
    assert refreshed_job is not None
    assert refreshed_job.tier_reached == 2
    assert refreshed_job.pages_fetched == 1
    assert refreshed_job.tokens_in == 310  # 300 (visual) + 10 (extraction)
    assert refreshed_job.tokens_out == 65  # 60 (visual) + 5 (extraction)
    assert float(refreshed_job.cost_usd) > 0

    events = list((await db.scalars(select(UsageEvent).where(UsageEvent.job_id == job.id))).all())
    kinds = {e.kind: e for e in events}
    assert set(kinds) == {UsageKind.DEEP_PROFILE, UsageKind.PROFILE}
    assert kinds[UsageKind.DEEP_PROFILE].tokens_in == 300
    assert kinds[UsageKind.PROFILE].tokens_in == 10

    pages = list((await db.scalars(select(ScrapePage).where(ScrapePage.job_id == job.id))).all())
    assert len(pages) == 1
    assert pages[0].screenshot_key is not None
    assert (tmp_path / pages[0].screenshot_key).read_bytes() == b"fake-png-bytes"
