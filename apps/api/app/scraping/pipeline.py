"""Runs one scrape job end to end: discover candidate pages, render them, extract a profile, and
write everything back — the company row, its offerings and competencies, and the job's own record
of what it did and cost. Pure orchestration; the actual work lives in discovery.py, render.py,
visual_agent.py, and extraction.py so each stays independently testable.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from playwright.async_api import async_playwright
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.errors import NoProfilingProvider
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
    ScrapeProvider,
    ScrapeStatus,
    SourceKind,
    Tenant,
    UsageKind,
)
from app.scraping.browser_use_cloud import MODEL as BROWSER_USE_MODEL
from app.scraping.browser_use_cloud import BrowserUseTaskFailed, run_browser_use_task
from app.scraping.discovery import discover_candidate_urls
from app.scraping.extraction import MODEL as EXTRACTION_MODEL
from app.scraping.extraction import ExtractedFacts, ExtractedProfile, extract_profile
from app.scraping.merge import merge_profiles
from app.scraping.render import RenderedPage, render_pages
from app.scraping.visual_agent import MODEL as VISUAL_MODEL
from app.scraping.visual_agent import explore_visually
from app.services.embeddings import MODEL_NAME, embed_texts
from app.services.llm import ResolvedKey, has_anthropic_key, resolve_anthropic_key, resolve_browser_use_key
from app.services.usage import record_usage_event

log = structlog.get_logger()

MAX_CANDIDATE_PAGES = 12
# Pricing at the time this was written — see docs/PLAN.md §5. A config constant, not a live
# lookup, so cost tracking degrades gracefully (a stale number, never a failed job) if pricing
# changes before this is updated.
_SONNET_INPUT_COST_PER_MTOK = Decimal("2.00")
_SONNET_OUTPUT_COST_PER_MTOK = Decimal("10.00")
_OPUS_INPUT_COST_PER_MTOK = Decimal("5.00")
_OPUS_OUTPUT_COST_PER_MTOK = Decimal("25.00")
# Browser Use Cloud bills by step, not by token — this platform has no visibility into their own
# per-call cost, so a flat per-step estimate is what usage_events records instead.
_BROWSER_USE_COST_PER_STEP = Decimal("0.01")


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


async def _run_browser_use(
    db: AsyncSession, *, job: ScrapeJob, company: Company, resolved: ResolvedKey, fatal: bool
) -> tuple[ExtractedProfile | None, list[RenderedPage]]:
    """Run a profiling task through Browser Use Cloud. When Tier 1's own Anthropic extraction can
    still produce a profile alongside this (`fatal=False` — the ordinary DEEP-mode case, Browser
    Use as a second Tier 2 provider per docs/PLAN.md §13), a failure here just means deep mode
    found nothing extra this run, the same graceful degradation Tier 0/1 already gives on their
    own. When Browser Use is the *only* extractor this workspace has (`fatal=True` — no Anthropic
    key configured at all, tenant or platform), its failure is the whole job's failure — there's
    nothing left to fall back to."""
    try:
        result = await run_browser_use_task(
            api_key=resolved.api_key, website_url=company.website_url, domain=company.domain
        )
    except BrowserUseTaskFailed as exc:
        log.warning(
            "browser_use_task_failed",
            tenant_id=str(job.tenant_id),
            job_id=str(job.id),
            fatal=fatal,
            error=str(exc),
        )
        if fatal:
            raise
        return None, []

    if result.steps:
        cost = _BROWSER_USE_COST_PER_STEP * result.steps
        job.cost_usd = float(Decimal(str(job.cost_usd)) + cost)
        await record_usage_event(
            db,
            tenant_id=job.tenant_id,
            job_id=job.id,
            kind=UsageKind.BROWSER_USE_RUN,
            model=BROWSER_USE_MODEL,
            tokens_in=0,
            tokens_out=0,
            cost_usd=float(cost),
            billed_to=resolved.billed_to,
        )
    return result.profile, result.pages


async def run_scrape_job(db: AsyncSession, *, job: ScrapeJob, company: Company) -> None:
    """Execute `job` against `company`. Raises on failure — the caller (the arq task) is what
    catches that and marks the job FAILED, matching how ReCore's own connector-indexing job
    separates "run the work" from "record that it broke" (see app/workers/index_connector.py)."""
    job.status = ScrapeStatus.RUNNING
    job.started_at = datetime.now(UTC)
    await db.flush()

    tenant = await db.get(Tenant, job.tenant_id)
    assert tenant is not None  # the job's own tenant, always present for an in-flight scrape

    resolved_key = await resolve_anthropic_key(db, tenant_id=job.tenant_id)
    anthropic_available = await has_anthropic_key(db, tenant_id=job.tenant_id)
    uses_browser_use_cloud = tenant.scrape_provider == ScrapeProvider.BROWSER_USE_CLOUD
    browser_use_key = (
        await resolve_browser_use_key(db, tenant_id=job.tenant_id) if uses_browser_use_cloud else None
    )

    if not anthropic_available and browser_use_key is None:
        # Nothing configured can extract a profile at all — fail now, before rendering pages this
        # job could never do anything with (a more useful signal than the raw Anthropic SDK error
        # `extract_profile` would otherwise raise deep into the job).
        raise NoProfilingProvider()

    # Browser Use Cloud runs as a second Tier 2 provider on every DEEP job that's chosen it
    # (docs/PLAN.md §13), and — when there's no Anthropic key to run Tier 1 extraction at all —
    # as the *only* extractor a FAST job on a Browser-Use-only workspace has.
    run_browser_use = browser_use_key is not None and (job.mode == ScrapeMode.DEEP or not anthropic_available)

    candidate_urls = await discover_candidate_urls(company.website_url, max_candidates=MAX_CANDIDATE_PAGES)
    job.tier_reached = 0

    rendered: list[RenderedPage] = []
    if candidate_urls:
        rendered = await render_pages(candidate_urls)
        job.tier_reached = 1
    elif job.mode == ScrapeMode.FAST and not run_browser_use:
        # Nothing to read and nowhere for a fast job to escalate to — done, nothing extracted.
        job.status = ScrapeStatus.DONE
        job.finished_at = datetime.now(UTC)
        company.profile_status = ProfileStatus.DONE
        company.last_profiled_at = job.finished_at
        return

    cloud_profile: ExtractedProfile | None = None
    evidence_pages: list[RenderedPage] = list(rendered)

    if run_browser_use:
        assert browser_use_key is not None  # implied by `run_browser_use`
        cloud_profile, cloud_pages = await _run_browser_use(
            db, job=job, company=company, resolved=browser_use_key, fatal=not anthropic_available
        )
        evidence_pages = evidence_pages + cloud_pages
        job.tier_reached = 2
    elif job.mode == ScrapeMode.DEEP:
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
        evidence_pages = evidence_pages + exploration.pages
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

    job.pages_fetched = len(evidence_pages)

    await db.execute(
        delete(ScrapePage).where(ScrapePage.tenant_id == job.tenant_id, ScrapePage.job_id == job.id)
    )
    for page in evidence_pages:
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

    # Only ever called with an Anthropic key actually configured — `anthropic_available` is what
    # the upfront check above guaranteed one of, and this is the branch that needs it; a
    # Browser-Use-only workspace's profile comes entirely from `cloud_profile` instead.
    result = await extract_profile(rendered, api_key=resolved_key.api_key) if anthropic_available else None
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

    # `result` is Tier 1's own extraction (None if there was nothing to send it); `cloud_profile`
    # is Browser Use Cloud's separately-extracted profile (None unless that provider ran and
    # succeeded). Either can be missing — only both missing means nothing to write at all.
    profile = result.profile if result is not None else None
    if cloud_profile is not None:
        profile = merge_profiles(profile, cloud_profile) if profile is not None else cloud_profile

    if profile is not None:
        company.overview = profile.overview
        _apply_facts(company, profile.facts)

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
            for item in profile.offerings
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
            for comp_item in profile.competencies
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
