"""Runs one scrape job end to end: discover candidate pages, render them, extract a profile, and
write everything back — the company row, its offerings and competencies, and the job's own record
of what it did and cost. Pure orchestration; the actual work lives in discovery.py, render.py, and
extraction.py so each stays independently testable.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete
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
)
from app.scraping.discovery import discover_candidate_urls
from app.scraping.extraction import extract_profile
from app.scraping.render import render_pages
from app.services.embeddings import MODEL_NAME, embed_texts

MAX_CANDIDATE_PAGES = 12
# Sonnet 5 pricing at the time this was written — see docs/PLAN.md §5. A config constant, not a
# live lookup, so cost tracking degrades gracefully (a stale number, never a failed job) if pricing
# changes before this is updated.
_INPUT_COST_PER_MTOK = Decimal("2.00")
_OUTPUT_COST_PER_MTOK = Decimal("10.00")


def _cost_usd(tokens_in: int, tokens_out: int) -> Decimal:
    return (
        Decimal(tokens_in) / 1_000_000 * _INPUT_COST_PER_MTOK
        + Decimal(tokens_out) / 1_000_000 * _OUTPUT_COST_PER_MTOK
    )


async def run_scrape_job(db: AsyncSession, *, job: ScrapeJob, company: Company) -> None:
    """Execute `job` against `company`. Raises on failure — the caller (the arq task) is what
    catches that and marks the job FAILED, matching how ReCore's own connector-indexing job
    separates "run the work" from "record that it broke" (see app/workers/index_connector.py)."""
    job.status = ScrapeStatus.RUNNING
    job.started_at = datetime.now(UTC)
    await db.flush()

    candidate_urls = await discover_candidate_urls(company.website_url, max_candidates=MAX_CANDIDATE_PAGES)
    job.tier_reached = 0
    if not candidate_urls:
        job.status = ScrapeStatus.DONE
        job.finished_at = datetime.now(UTC)
        company.profile_status = ProfileStatus.DONE
        company.last_profiled_at = job.finished_at
        return

    rendered = await render_pages(candidate_urls)
    job.tier_reached = 1
    job.pages_fetched = len(rendered)

    await db.execute(
        delete(ScrapePage).where(ScrapePage.tenant_id == job.tenant_id, ScrapePage.job_id == job.id)
    )
    for page in rendered:
        db.add(
            ScrapePage(
                tenant_id=job.tenant_id,
                job_id=job.id,
                url=page.final_url,
                status_code=page.status_code,
                content_hash=page.content_hash,
                markdown=page.markdown,
            )
        )

    # Committed here, ahead of the one step in this whole job that calls out to a third-party API
    # and can fail for reasons entirely outside this pipeline's control (a missing or rate-limited
    # key, a network blip). Without this, an extraction failure would roll back everything above
    # it too — Tier 1 having actually rendered N pages successfully is exactly the fact a
    # job-status view most needs to survive that failure, not disappear along with it.
    await db.commit()
    await set_tenant_scope(db, job.tenant_id)  # transaction-local — reset after the commit above

    result = await extract_profile(rendered)
    if result is not None:
        job.tokens_in = result.tokens_in
        job.tokens_out = result.tokens_out
        job.cost_usd = float(_cost_usd(result.tokens_in, result.tokens_out))

        company.overview = result.profile.overview

        await db.execute(
            delete(Offering).where(Offering.tenant_id == company.tenant_id, Offering.company_id == company.id)
        )
        offerings = [
            Offering(
                tenant_id=company.tenant_id,
                company_id=company.id,
                kind=item.kind,
                name=item.name,
                description=item.description,
                category=item.category,
                evidence=[e.model_dump() for e in item.evidence],
            )
            for item in result.profile.offerings
        ]
        db.add_all(offerings)

        await db.execute(
            delete(Competency).where(
                Competency.tenant_id == company.tenant_id, Competency.company_id == company.id
            )
        )
        competencies = [
            Competency(
                tenant_id=company.tenant_id,
                company_id=company.id,
                kind=comp_item.kind,
                name=comp_item.name,
                description=comp_item.description,
                evidence=[e.model_dump() for e in comp_item.evidence],
            )
            for comp_item in result.profile.competencies
        ]
        db.add_all(competencies)

        # Flushed (not committed) so the mapper's own flush-time id default (UUIDPrimaryKeyMixin)
        # actually populates offering.id/competency.id — needed as embeddings' own source_id.
        await db.flush()
        await _embed_profile(db, company=company, offerings=offerings, competencies=competencies)

    job.status = ScrapeStatus.DONE
    job.finished_at = datetime.now(UTC)
    company.profile_status = ProfileStatus.DONE
    company.last_profiled_at = job.finished_at


async def _embed_profile(
    db: AsyncSession, *, company: Company, offerings: list[Offering], competencies: list[Competency]
) -> None:
    """Embed the company's summary plus every offering and competency, replacing whatever this
    company had before. Best-effort: a down or slow embeddings service degrades the company to
    "profiled but not yet searchable" rather than failing a scrape that otherwise succeeded — the
    next re-profile embeds it again, and search simply excludes it until then.
    """
    texts: list[str] = []
    sources: list[tuple[SourceKind, uuid.UUID]] = []
    if company.overview:
        texts.append(company.overview)
        sources.append((SourceKind.COMPANY_SUMMARY, company.id))
    for offering in offerings:
        texts.append(f"{offering.name}: {offering.description}" if offering.description else offering.name)
        sources.append((SourceKind.OFFERING, offering.id))
    for competency in competencies:
        texts.append(
            f"{competency.name}: {competency.description}" if competency.description else competency.name
        )
        sources.append((SourceKind.COMPETENCY, competency.id))
    if not texts:
        return

    try:
        vectors = await embed_texts(texts)
    except Exception:  # noqa: BLE001 — see this function's own docstring
        return

    await db.execute(
        delete(Embedding).where(Embedding.tenant_id == company.tenant_id, Embedding.company_id == company.id)
    )
    for (source_kind, source_id), text, vector in zip(sources, texts, vectors, strict=True):
        db.add(
            Embedding(
                tenant_id=company.tenant_id,
                company_id=company.id,
                source_kind=source_kind,
                source_id=source_id,
                content=text,
                embedding=vector,
                model=MODEL_NAME,
            )
        )


__all__ = ["run_scrape_job", "MAX_CANDIDATE_PAGES"]
