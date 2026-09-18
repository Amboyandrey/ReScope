"""Tier 1's extraction step — one structured-output call turns a company's rendered pages into
its profile: an overview, its products and services, and its competencies, each traceable back to
the page and quote it came from.

Runs on `claude-sonnet-5` at low/medium effort (see docs/PLAN.md §5) — bulk schema-fill from text
that's already been rendered and cleaned, not a task that needs a frontier model's judgment.
"""

import anthropic
from pydantic import BaseModel, Field, field_validator

from app.core.config import get_settings
from app.models.company import CompanyType
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
    description: str = Field(
        description="What this offering is. Omit the offering entirely if you can't write a real one."
    )
    category: str | None = None
    evidence: list[ExtractedEvidence]


class ExtractedCompetency(BaseModel):
    kind: str = Field(
        description='One of "capability", "technology", "certification", "industry_served", "partnership"'
    )
    name: str
    description: str = Field(
        description=(
            "How the company evidently has this — a certification it holds, a technology named "
            "on a product page, a case study in that industry. Not a restatement of the name. "
            "Omit the competency entirely if you can't write a real one."
        )
    )
    evidence: list[ExtractedEvidence]


class ExtractedFacts(BaseModel):
    """Company-level facts pulled from about/contact/footer pages — every field stays null rather
    than guessed when the pages don't actually state it."""

    hq_country: str | None = Field(default=None, description="ISO 3166-1 alpha-2, e.g. 'US', 'DE'.")
    hq_city: str | None = None
    industry: str | None = None
    company_type: CompanyType | None = None
    employee_range: str | None = Field(default=None, description="e.g. '1-10', '11-50', '1000+'.")
    founded_year: int | None = None
    socials: dict[str, str] = Field(default_factory=dict, description="e.g. {'linkedin': 'https://...'}")

    @field_validator("socials", mode="before")
    @classmethod
    def _null_socials_means_none_found(cls, value: object) -> object:
        """Browser Use Cloud's own model (`app/scraping/browser_use_cloud.py`) has been observed
        sending an explicit JSON `null` here — the same "nothing here" a scalar fact would use —
        even though the schema asks for an object. `default_factory` only covers the field being
        *omitted*, not set to `null`, so without this an otherwise-successful task fails
        `model_validate_json` entirely over one empty field."""
        return {} if value is None else value


class ExtractedProfile(BaseModel):
    """What one extraction call produces from a company's own pages."""

    overview: str = Field(description="A neutral 2-4 sentence summary of what the company does.")
    facts: ExtractedFacts = Field(default_factory=ExtractedFacts)
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
        "Below are pages from one company's own website. Extract its overview, the company facts "
        "listed in the schema (country as an ISO 3166-1 alpha-2 code, city, industry, company "
        "type, employee range, founded year, social links) — leave a fact null rather than guess "
        "if these pages don't actually state it — the products and services it offers, and its "
        "competencies (capabilities, technologies, certifications, industries it serves, and "
        "partnerships). Only include what these pages actually support — do not invent offerings "
        "or competencies. Every offering and competency needs a real description (what it is for "
        "an offering; the evidence-backed reason the company has it — a held certification, a "
        "named technology, a case study — for a competency, never just its name restated) and at "
        "least one evidence entry citing the exact page URL it came from and a short supporting "
        "quote lifted from that page's text. Omit an offering or competency entirely rather than "
        "include it without a real description.\n\n"
        "If a page lists several individually-named or branded products or technologies (for "
        "example, cards or tiles each with their own name, like 'TargetHeat' or 'LaserRaster'), "
        "extract each one as its own separate offering using that real name — never collapse them "
        "into one generic offering describing the product line, catalogue, or platform as a "
        "whole. A generic description of the company's own site or process (e.g. 'browse our "
        "catalogue', 'register as a partner') is not itself a product or service and should be "
        "omitted unless the company genuinely sells that access or process as an offering.\n\n"
        f"{pages_block}"
    )


async def extract_profile(
    pages: list[RenderedPage], *, api_key: str | None = None
) -> ExtractionResult | None:
    """Run the extraction call, or `None` if there was nothing worth sending the model. `api_key`
    is the resolved key from `app.services.llm.resolve_anthropic_key` — the platform's own when
    omitted, e.g. in a test that doesn't care which key is used."""
    if not pages:
        return None
    settings = get_settings()
    client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key or None)
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
