"""Runs one scrape job end to end: discover candidate pages, render them, extract a profile, and
write everything back — the company row, its offerings and competencies, and the job's own record
of what it did and cost. Pure orchestration; the actual work lives in discovery.py, render.py,
visual_agent.py, and extraction.py so each stays independently testable.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from playwright.async_api import async_playwright
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.storage import save_screenshot
from app.models import (
    Company,
    Competency,
    Embedding,
    Offering,
    ProfileStatus,
    ScrapeJob,
    ScrapeMode,
    ScrapePage,
    ScrapeStatus,
    SourceKind,
    UsageKind,
)
from app.scraping.discovery import discover_candidate_urls
from app.scraping.extraction import MODEL as EXTRACTION_MODEL
from app.scraping.extraction import ExtractedFacts, extract_profile
from app.scraping.render import RenderedPage, render_pages
from app.scraping.visual_agent import MODEL as VISUAL_MODEL
from app.scraping.visual_agent import explore_visually
from app.services.embeddings import MODEL_NAME, embed_texts
from app.services.llm import resolve_anthropic_key
from app.services.usage import record_usage_event

MAX_CANDIDATE_PAGES = 12
# Pricing at the time this was written — see docs/PLAN.md §5. A config constant, not a live
# lookup, so cost tracking degrades gracefully (a stale number, never a failed job) if pricing
# changes before this is updated.
_SONNET_INPUT_COST_PER_MTOK = Decimal("2.00")
_SONNET_OUTPUT_COST_PER_MTOK = Decimal("10.00")
_OPUS_INPUT_COST_PER_MTOK = Decimal("5.00")
_OPUS_OUTPUT_COST_PER_MTOK = Decimal("25.00")


def _cost_usd(tokens_in: int, tokens_out: int, *, input_rate: Decimal, output_rate: Decimal) -> Decimal:
    return Decimal(tokens_in) / 1_000_000 * input_rate + Decimal(tokens_out) / 1_000_000 * output_rate


def _clean_country_code(code: str | None) -> str | None:
    """Two-letter ISO 3166-1 alpha-2 or nothing — the model is told to use this format, but this
    is what actually keeps a longer free-text guess from overflowing the column or corrupting the
    catalogue's country filter with something no other company's row will ever match."""
    if code and len(code) == 2 and code.isalpha():
        return code.upper()
    return None


def _apply_facts(company: Company, facts: ExtractedFacts) -> None:
    """Write extraction's company-level facts onto `company`, truncating anything that (despite
    the prompt) came back longer than its column — a formatting slip in one field shouldn't fail
    an otherwise-successful scrape."""
    company.hq_country = _clean_country_code(facts.hq_country)
    company.hq_city = facts.hq_city[:120] if facts.hq_city else None
    company.industry = facts.industry[:120] if facts.industry else None
    company.company_type = facts.company_type
    company.employee_range = facts.employee_range[:32] if facts.employee_range else None
    company.founded_year = facts.founded_year
    company.socials = facts.socials


async def run_scrape_job(db: AsyncSession, *, job: ScrapeJob, company: Company) -> None:
    """Execute `job` against `company`. Raises on failure — the caller (the arq task) is what
    catches that and marks the job FAILED, matching how ReCore's own connector-indexing job
    separates "run the work" from "record that it broke" (see app/workers/index_connector.py)."""
    job.status = ScrapeStatus.RUNNING
    job.started_at = datetime.now(UTC)
    await db.flush()

    resolved_key = await resolve_anthropic_key(db, tenant_id=job.tenant_id)

    candidate_urls = await discover_candidate_urls(company.website_url, max_candidates=MAX_CANDIDATE_PAGES)
    job.tier_reached = 0

    rendered: list[RenderedPage] = []
    if candidate_urls:
        rendered = await render_pages(candidate_urls)
        job.tier_reached = 1
    elif job.mode == ScrapeMode.FAST:
        # Nothing to read and nowhere for a fast job to escalate to — done, nothing extracted.
        job.status = ScrapeStatus.DONE
        job.finished_at = datetime.now(UTC)
        company.profile_status = ProfileStatus.DONE
        company.last_profiled_at = job.finished_at
        return

    if job.mode == ScrapeMode.DEEP:
        # Explores from the homepage directly rather than Tier 0's candidate list — the whole
        # point of Tier 2 is finding content no static link ever pointed at (behind a tab, an
        # accordion, a "load more" button), so it isn't limited to what Tier 0 already found.
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox"])
            try:
                exploration = await explore_visually(
                    browser, company.website_url, api_key=resolved_key.api_key
                )
            finally:
                await browser.close()
        job.tier_reached = 2
        rendered = rendered + exploration.pages
        if exploration.tokens_in or exploration.tokens_out:
            deep_cost = _cost_usd(
                exploration.tokens_in,
                exploration.tokens_out,
                input_rate=_OPUS_INPUT_COST_PER_MTOK,
                output_rate=_OPUS_OUTPUT_COST_PER_MTOK,
            )
            job.tokens_in += exploration.tokens_in
            job.tokens_out += exploration.tokens_out
            job.cost_usd = float(Decimal(str(job.cost_usd)) + deep_cost)
            await record_usage_event(
                db,
                tenant_id=job.tenant_id,
                job_id=job.id,
                kind=UsageKind.DEEP_PROFILE,
                model=VISUAL_MODEL,
                tokens_in=exploration.tokens_in,
                tokens_out=exploration.tokens_out,
                cost_usd=float(deep_cost),
                billed_to=resolved_key.billed_to,
            )

    job.pages_fetched = len(rendered)

    await db.execute(
        delete(ScrapePage).where(ScrapePage.tenant_id == job.tenant_id, ScrapePage.job_id == job.id)
    )
    for page in rendered:
        screenshot_key = save_screenshot(job.tenant_id, job.id, page.screenshot) if page.screenshot else None
        db.add(
            ScrapePage(
                tenant_id=job.tenant_id,
                job_id=job.id,
                url=page.final_url,
                status_code=page.status_code,
                content_hash=page.content_hash,
                markdown=page.markdown,
                screenshot_key=screenshot_key,
            )
        )

    # Committed here, ahead of the one step in this whole job that calls out to a third-party API
    # and can fail for reasons entirely outside this pipeline's control (a missing or rate-limited
    # key, a network blip). Without this, an extraction failure would roll back everything above
    # it too — Tier 1 (and Tier 2's own exploration) having actually succeeded is exactly the fact
    # a job-status view most needs to survive that failure, not disappear along with it.
    await db.commit()
    await set_tenant_scope(db, job.tenant_id)  # transaction-local — reset after the commit above

    result = await extract_profile(rendered, api_key=resolved_key.api_key)
    if result is not None:
        job.tokens_in += result.tokens_in
        job.tokens_out += result.tokens_out
        profile_cost = _cost_usd(
            result.tokens_in,
            result.tokens_out,
            input_rate=_SONNET_INPUT_COST_PER_MTOK,
            output_rate=_SONNET_OUTPUT_COST_PER_MTOK,
        )
        job.cost_usd = float(Decimal(str(job.cost_usd)) + profile_cost)
        # A profile run is billed the moment extraction succeeds, independent of whether
        # embedding it afterward also succeeds — extraction is the step this platform pays
        # Anthropic for; a slow or down embeddings service doesn't change that cost.
        await record_usage_event(
            db,
            tenant_id=job.tenant_id,
            job_id=job.id,
            kind=UsageKind.PROFILE,
            model=EXTRACTION_MODEL,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=float(profile_cost),
            billed_to=resolved_key.billed_to,
        )

        company.overview = result.profile.overview
        _apply_facts(company, result.profile.facts)

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


def _company_summary_text(company: Company) -> str | None:
    """The text a query like "robotics manufacturer in Germany" needs to match against — facts up
    front, since a query naming a type or a place should land on this row and not only on a
    specific offering that happens to mention it."""
    if not company.overview:
        return None
    lead_parts = [company.name]
    if company.company_type:
        place = ", ".join(p for p in (company.hq_city, company.hq_country) if p)
        lead_parts.append(f"{company.company_type.value} in {place}" if place else company.company_type.value)
    elif company.hq_city or company.hq_country:
        lead_parts.append(", ".join(p for p in (company.hq_city, company.hq_country) if p))
    lead = " — ".join(lead_parts)
    industry = f" {company.industry}." if company.industry else ""
    return f"{lead}.{industry} {company.overview}"


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
    summary = _company_summary_text(company)
    if summary:
        texts.append(summary)
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
