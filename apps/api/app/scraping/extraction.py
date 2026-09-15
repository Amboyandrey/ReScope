"""Tier 1's extraction step — one structured-output call turns a company's rendered pages into
its profile: an overview, its products and services, and its competencies, each traceable back to
the page and quote it came from.

Runs on `claude-sonnet-5` at low/medium effort (see docs/PLAN.md §5) — bulk schema-fill from text
that's already been rendered and cleaned, not a task that needs a frontier model's judgment.
"""

import anthropic
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.scraping.render import RenderedPage

MODEL = "claude-sonnet-5"
MAX_OUTPUT_TOKENS = 8000
# Pages are already capped per-page (render.py); this bounds the whole prompt across all of them,
# so a job with many long pages can't silently balloon the request past the model's context.
MAX_TOTAL_PROMPT_CHARS = 60_000


class ExtractedEvidence(BaseModel):
    url: str = Field(description="Which of the provided pages this came from — copy it exactly.")
    quote: str = Field(description="A short supporting phrase or sentence, taken from that page.")


class ExtractedOffering(BaseModel):
    kind: str = Field(description='"product" or "service"')
    name: str
    description: str | None = None
    category: str | None = None
    evidence: list[ExtractedEvidence]


class ExtractedCompetency(BaseModel):
    kind: str = Field(
        description='One of "capability", "technology", "certification", "industry_served", "partnership"'
    )
    name: str
    description: str | None = None
    evidence: list[ExtractedEvidence]


class ExtractedProfile(BaseModel):
    """What one extraction call produces from a company's own pages."""

    overview: str = Field(description="A neutral 2-4 sentence summary of what the company does.")
    offerings: list[ExtractedOffering]
    competencies: list[ExtractedCompetency]


class ExtractionResult(BaseModel):
    profile: ExtractedProfile
    tokens_in: int
    tokens_out: int


def _build_prompt(pages: list[RenderedPage]) -> str:
    """One prompt block per page, each labeled with the URL evidence must cite back to."""
    sections = []
    budget = MAX_TOTAL_PROMPT_CHARS
    for page in pages:
        if budget <= 0:
            break
        chunk = page.markdown[:budget]
        budget -= len(chunk)
        sections.append(f"### Page: {page.url}\n\n{chunk}")
    pages_block = "\n\n---\n\n".join(sections)
    return (
        "Below are pages from one company's own website. Extract its overview, the products and "
        "services it offers, and its competencies (capabilities, technologies, certifications, "
        "industries it serves, and partnerships). Only include what these pages actually support "
        "— do not invent offerings or competencies. Every offering and competency needs at least "
        "one evidence entry citing the exact page URL it came from and a short supporting quote "
        "lifted from that page's text.\n\n"
        f"{pages_block}"
    )


async def extract_profile(pages: list[RenderedPage]) -> ExtractionResult | None:
    """Run the extraction call, or `None` if there was nothing worth sending the model."""
    if not pages:
        return None
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key or None)
    response = await client.messages.parse(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": _build_prompt(pages)}],
        output_format=ExtractedProfile,
    )
    return ExtractionResult(
        profile=response.parsed_output,
        tokens_in=response.usage.input_tokens,
        tokens_out=response.usage.output_tokens,
    )
