"""Combining Tier 1's own extraction with a second Tier 2 provider's separately-extracted profile
(docs/PLAN.md §13, Browser Use Cloud). Offerings and competencies merge by case-insensitive name,
keeping whichever copy says more and the union of their evidence; facts prefer Tier 1's own,
falling back per field only where Tier 1 came up empty.
"""

from app.scraping.extraction import (
    ExtractedCompetency,
    ExtractedEvidence,
    ExtractedFacts,
    ExtractedOffering,
    ExtractedProfile,
)


def _merge_facts(primary: ExtractedFacts, secondary: ExtractedFacts) -> ExtractedFacts:
    return ExtractedFacts(
        hq_country=primary.hq_country or secondary.hq_country,
        hq_city=primary.hq_city or secondary.hq_city,
        industry=primary.industry or secondary.industry,
        company_type=primary.company_type or secondary.company_type,
        employee_range=primary.employee_range or secondary.employee_range,
        founded_year=primary.founded_year or secondary.founded_year,
        socials={**secondary.socials, **primary.socials},
    )


def _union_evidence(a: list[ExtractedEvidence], b: list[ExtractedEvidence]) -> list[ExtractedEvidence]:
    seen = {(e.url, e.quote) for e in a}
    return a + [e for e in b if (e.url, e.quote) not in seen]


def _merge_offerings(
    primary: list[ExtractedOffering], secondary: list[ExtractedOffering]
) -> list[ExtractedOffering]:
    by_name: dict[str, ExtractedOffering] = {o.name.strip().lower(): o for o in primary}
    for item in secondary:
        key = item.name.strip().lower()
        existing = by_name.get(key)
        if existing is None:
            by_name[key] = item
            continue
        winner = item if len(item.description) > len(existing.description) else existing
        by_name[key] = winner.model_copy(
            update={"evidence": _union_evidence(existing.evidence, item.evidence)}
        )
    return list(by_name.values())


def _merge_competencies(
    primary: list[ExtractedCompetency], secondary: list[ExtractedCompetency]
) -> list[ExtractedCompetency]:
    by_name: dict[str, ExtractedCompetency] = {c.name.strip().lower(): c for c in primary}
    for item in secondary:
        key = item.name.strip().lower()
        existing = by_name.get(key)
        if existing is None:
            by_name[key] = item
            continue
        winner = item if len(item.description) > len(existing.description) else existing
        by_name[key] = winner.model_copy(
            update={"evidence": _union_evidence(existing.evidence, item.evidence)}
        )
    return list(by_name.values())


def merge_profiles(primary: ExtractedProfile, secondary: ExtractedProfile) -> ExtractedProfile:
    """Combine `primary` (Tier 1's own extraction) with `secondary` (a second Tier 2 provider's).
    Order only matters for which side's overview and facts win on a tie."""
    return ExtractedProfile(
        overview=primary.overview or secondary.overview,
        facts=_merge_facts(primary.facts, secondary.facts),
        offerings=_merge_offerings(primary.offerings, secondary.offerings),
        competencies=_merge_competencies(primary.competencies, secondary.competencies),
    )
