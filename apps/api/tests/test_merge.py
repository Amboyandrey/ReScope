"""Merging Tier 1's own extraction with a second Tier 2 provider's separately-extracted profile."""

from app.scraping.extraction import (
    ExtractedCompetency,
    ExtractedEvidence,
    ExtractedFacts,
    ExtractedOffering,
    ExtractedProfile,
)
from app.scraping.merge import merge_profiles


def _offering(
    name: str, description: str, *, evidence: list[ExtractedEvidence] | None = None
) -> ExtractedOffering:
    return ExtractedOffering(
        kind="product",
        name=name,
        description=description,
        category=None,
        evidence=evidence or [ExtractedEvidence(url="https://example.com", quote="evidence")],
    )


def _competency(
    name: str, description: str, *, evidence: list[ExtractedEvidence] | None = None
) -> ExtractedCompetency:
    return ExtractedCompetency(
        kind="technology",
        name=name,
        description=description,
        evidence=evidence or [ExtractedEvidence(url="https://example.com", quote="evidence")],
    )


def test_offerings_with_different_names_are_both_kept() -> None:
    primary = ExtractedProfile(overview="A", offerings=[_offering("Widget", "x")], competencies=[])
    secondary = ExtractedProfile(overview="B", offerings=[_offering("Gadget", "y")], competencies=[])
    merged = merge_profiles(primary, secondary)
    assert {o.name for o in merged.offerings} == {"Widget", "Gadget"}


def test_offerings_matched_case_insensitively_keep_the_longer_description() -> None:
    primary = ExtractedProfile(overview="A", offerings=[_offering("Widget", "short")], competencies=[])
    secondary = ExtractedProfile(
        overview="B", offerings=[_offering("WIDGET", "a much longer description")], competencies=[]
    )
    merged = merge_profiles(primary, secondary)
    [offering] = merged.offerings
    assert offering.description == "a much longer description"


def test_offerings_union_their_evidence_without_duplicates() -> None:
    shared = ExtractedEvidence(url="https://example.com/products", quote="shared quote")
    primary = ExtractedProfile(
        overview="A",
        offerings=[_offering("Widget", "short", evidence=[shared])],
        competencies=[],
    )
    secondary = ExtractedProfile(
        overview="B",
        offerings=[
            _offering(
                "widget",
                "a longer description",
                evidence=[shared, ExtractedEvidence(url="https://example.com/other", quote="new quote")],
            )
        ],
        competencies=[],
    )
    merged = merge_profiles(primary, secondary)
    [offering] = merged.offerings
    assert len(offering.evidence) == 2


def test_competencies_merge_the_same_way_as_offerings() -> None:
    primary = ExtractedProfile(overview="A", offerings=[], competencies=[_competency("SOC 2", "short")])
    secondary = ExtractedProfile(
        overview="B", offerings=[], competencies=[_competency("soc 2", "a longer, evidence-backed reason")]
    )
    merged = merge_profiles(primary, secondary)
    [competency] = merged.competencies
    assert competency.description == "a longer, evidence-backed reason"


def test_facts_prefer_primary_and_fall_back_per_field() -> None:
    primary = ExtractedProfile(
        overview="A",
        facts=ExtractedFacts(hq_country="DE", hq_city=None, industry="Robotics"),
        offerings=[],
        competencies=[],
    )
    secondary = ExtractedProfile(
        overview="B",
        facts=ExtractedFacts(hq_country="US", hq_city="Berlin", industry="Manufacturing"),
        offerings=[],
        competencies=[],
    )
    merged = merge_profiles(primary, secondary)
    assert merged.facts.hq_country == "DE"  # primary wins when both have it
    assert merged.facts.hq_city == "Berlin"  # falls back to secondary when primary is empty
    assert merged.facts.industry == "Robotics"


def test_overview_falls_back_to_secondary_when_primary_is_empty() -> None:
    primary = ExtractedProfile(overview="", offerings=[], competencies=[])
    secondary = ExtractedProfile(overview="Secondary overview", offerings=[], competencies=[])
    merged = merge_profiles(primary, secondary)
    assert merged.overview == "Secondary overview"
