"""Semantic search over a tenant's companies, and finding companies similar to one another —
both just a cosine-distance ordering over `embeddings`, scoped by tenant."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Embedding, SourceKind
from app.services.embeddings import embed_text

# A cosine distance above this isn't a match worth showing — pgvector's cosine_distance is
# 1 - cosine_similarity, so 0 is identical and 2 is opposite; 0.6 keeps genuinely unrelated
# results out without being so strict that a middling but real match gets dropped.
MAX_DISTANCE = 0.6


@dataclass(frozen=True)
class SearchHit:
    company: Company
    source_kind: SourceKind
    content: str
    distance: float


async def semantic_search(
    db: AsyncSession, *, tenant_id: uuid.UUID, query: str, limit: int = 20
) -> list[SearchHit]:
    """Embed `query` and return the closest offerings/competencies/summaries across the tenant's
    companies, best match per company kept (a company matching on three different offerings
    shouldn't crowd out the next-best company that only matched once)."""
    query_vector = await embed_text(query)
    distance = Embedding.embedding.cosine_distance(query_vector)
    stmt = (
        select(Embedding, Company, distance.label("distance"))
        .join(Company, Embedding.company_id == Company.id)
        .where(Embedding.tenant_id == tenant_id, distance <= MAX_DISTANCE)
        .order_by(distance)
        .limit(limit * 4)
    )
    rows = (await db.execute(stmt)).all()

    hits: list[SearchHit] = []
    seen_companies: set[uuid.UUID] = set()
    for embedding, company, dist in rows:
        if company.id in seen_companies:
            continue
        seen_companies.add(company.id)
        hits.append(
            SearchHit(
                company=company,
                source_kind=embedding.source_kind,
                content=embedding.content,
                distance=float(dist),
            )
        )
        if len(hits) >= limit:
            break
    return hits


async def similar_companies(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, limit: int = 10
) -> list[tuple[Company, float]]:
    """Companies whose own summary embedding is closest to this one's — same tenant, self excluded."""
    own = await db.scalar(
        select(Embedding).where(
            Embedding.tenant_id == tenant_id,
            Embedding.source_kind == SourceKind.COMPANY_SUMMARY,
            Embedding.source_id == company_id,
        )
    )
    if own is None:
        return []

    distance = Embedding.embedding.cosine_distance(own.embedding)
    stmt = (
        select(Company, distance.label("distance"))
        .join(Embedding, Embedding.company_id == Company.id)
        .where(
            Embedding.tenant_id == tenant_id,
            Embedding.source_kind == SourceKind.COMPANY_SUMMARY,
            Company.id != company_id,
        )
        .order_by(distance)
        .limit(limit)
    )
    return [(company, float(dist)) for company, dist in (await db.execute(stmt)).all()]
