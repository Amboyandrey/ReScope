"""Retrieval-grounded chat over a tenant's catalogue (docs/PLAN.md §14): embedding the question,
pulling the closest rows across every company (not deduped to one per company — an answer wants
every relevant row, unlike search's own per-company best match), rendering them into a context
block the model answers from, and resolving citations from that same context afterward so a
citation is always a real row, never a hallucinated name.
"""

import re
import uuid
from dataclasses import dataclass, replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConversationNotFound
from app.models import (
    Company,
    Conversation,
    Embedding,
    Message,
    MessageRole,
    SourceKind,
)
from app.services.catalogue import CatalogueFilters, list_catalogue
from app.services.embeddings import embed_text
from app.services.search import MAX_DISTANCE

RETRIEVAL_LIMIT = 12
HISTORY_LIMIT = 10

_COMPANY_TYPE_LABELS = {
    "manufacturer": "Manufacturer",
    "distributor": "Distributor",
    "service_provider": "Service provider",
    "software": "Software",
    "consultancy": "Consultancy",
    "agency": "Agency",
    "research": "Research",
    "other": "Other",
}


@dataclass(frozen=True)
class RetrievedItem:
    company: Company
    source_kind: SourceKind
    source_id: uuid.UUID
    content: str
    distance: float


async def _filtered_company_ids(
    db: AsyncSession, *, tenant_id: uuid.UUID, filters: CatalogueFilters | None
) -> set[uuid.UUID] | None:
    """`None` means "no filter narrowing" — every other catalogue filter besides `q` narrows
    retrieval the same way it narrows the catalogue view itself."""
    if filters is None:
        return None
    narrowing = (
        filters.country,
        filters.company_type,
        filters.industry,
        filters.competency_kind,
        filters.tag_id,
    )
    if not any(narrowing):
        return None
    companies = await list_catalogue(db, tenant_id=tenant_id, filters=replace(filters, q=None), limit=1000)
    return {c.id for c in companies}


async def retrieve_context(
    db: AsyncSession, *, tenant_id: uuid.UUID, query: str, filters: CatalogueFilters | None = None
) -> list[RetrievedItem]:
    """The closest `RETRIEVAL_LIMIT` embedding rows to `query`, optionally narrowed to companies
    matching `filters` first."""
    company_ids = await _filtered_company_ids(db, tenant_id=tenant_id, filters=filters)
    query_vector = await embed_text(query)
    distance = Embedding.embedding.cosine_distance(query_vector)
    stmt = (
        select(Embedding, Company, distance.label("distance"))
        .join(Company, Embedding.company_id == Company.id)
        .where(Embedding.tenant_id == tenant_id, distance <= MAX_DISTANCE)
    )
    if company_ids is not None:
        stmt = stmt.where(Company.id.in_(company_ids))
    stmt = stmt.order_by(distance).limit(RETRIEVAL_LIMIT)
    rows = (await db.execute(stmt)).all()
    return [
        RetrievedItem(
            company=company,
            source_kind=embedding.source_kind,
            source_id=embedding.source_id,
            content=embedding.content,
            distance=float(dist),
        )
        for embedding, company, dist in rows
    ]


def _facts_line(company: Company) -> str:
    parts = []
    if company.company_type:
        parts.append(_COMPANY_TYPE_LABELS.get(company.company_type.value, company.company_type.value))
    place = ", ".join(p for p in (company.hq_city, company.hq_country) if p)
    if place:
        parts.append(place)
    if company.industry:
        parts.append(company.industry)
    return " · ".join(parts)


def build_context(items: list[RetrievedItem]) -> str:
    """One block per company named in `items`, in first-seen (closest-match-first) order."""
    order: list[uuid.UUID] = []
    by_company: dict[uuid.UUID, list[RetrievedItem]] = {}
    for item in items:
        if item.company.id not in by_company:
            by_company[item.company.id] = []
            order.append(item.company.id)
        by_company[item.company.id].append(item)

    blocks = []
    for company_id in order:
        company_items = by_company[company_id]
        company = company_items[0].company
        lines = [f"### {company.name}"]
        facts = _facts_line(company)
        if facts:
            lines.append(facts)
        if company.overview:
            lines.append(company.overview)
        for item in company_items:
            lines.append(f"- ({item.source_kind.value}) {item.content}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


_CITATION_PATTERN = re.compile(r"\[([^\[\]]+)\]")


def resolve_citations(answer_text: str, items: list[RetrievedItem]) -> list[dict[str, str]]:
    """Every `[Company Name]` in `answer_text` that names a company actually present in `items`,
    citing that company's own closest-matching retrieved row. A bracketed name that doesn't match
    anything in context is silently dropped rather than cited — it was never grounded to begin
    with, whatever the model meant by it."""
    best_by_name: dict[str, RetrievedItem] = {}
    for item in items:
        current = best_by_name.get(item.company.name)
        if current is None or item.distance < current.distance:
            best_by_name[item.company.name] = item

    seen: set[str] = set()
    citations: list[dict[str, str]] = []
    for name in _CITATION_PATTERN.findall(answer_text):
        if name in seen:
            continue
        matched = best_by_name.get(name)
        if matched is None:
            continue
        seen.add(name)
        citations.append(
            {
                "company_id": str(matched.company.id),
                "source_kind": matched.source_kind.value,
                "source_id": str(matched.source_id),
            }
        )
    return citations


SYSTEM_PROMPT = (
    "You are answering questions about the companies in this workspace's catalogue, using only "
    "the context provided below — never anything you already know about a real company by that "
    "name. If the context doesn't support an answer, say so plainly rather than guessing. Cite "
    "every company you draw from by wrapping its exact name in square brackets, e.g. [Acme Corp], "
    "the first time you mention it in your answer."
)


async def create_conversation(
    db: AsyncSession, *, tenant_id: uuid.UUID, owner_id: uuid.UUID, title: str
) -> Conversation:
    conversation = Conversation(tenant_id=tenant_id, owner_id=owner_id, title=title.strip() or "New chat")
    db.add(conversation)
    await db.flush()
    return conversation


async def list_conversations(
    db: AsyncSession, *, tenant_id: uuid.UUID, owner_id: uuid.UUID
) -> list[Conversation]:
    stmt = (
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id, Conversation.owner_id == owner_id)
        .order_by(Conversation.updated_at.desc())
    )
    return list((await db.scalars(stmt)).all())


async def get_conversation(
    db: AsyncSession, *, tenant_id: uuid.UUID, owner_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    """Scoped by owner, not just tenant — a conversation is personal, like a saved search; a
    teammate naming its id gets the same 404 a nonexistent one would."""
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.id == conversation_id,
            Conversation.owner_id == owner_id,
        )
    )
    if conversation is None:
        raise ConversationNotFound()
    return conversation


async def delete_conversation(
    db: AsyncSession, *, tenant_id: uuid.UUID, owner_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    conversation = await get_conversation(
        db, tenant_id=tenant_id, owner_id=owner_id, conversation_id=conversation_id
    )
    await db.delete(conversation)
    await db.flush()


async def list_messages(
    db: AsyncSession, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[Message]:
    stmt = (
        select(Message)
        .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list((await db.scalars(stmt)).all())


async def recent_history_for_prompt(
    db: AsyncSession, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[dict[str, str]]:
    """The last `HISTORY_LIMIT` turns, oldest first, as Anthropic message dicts — retrieval only
    ever runs on the newest question, so this is just conversational continuity, not more context.

    Built from `list_messages`'s own ascending order and sliced from the end, rather than a
    separate descending-then-reversed query — two messages can share the exact same `created_at`
    (Postgres's `now()` is frozen for the whole transaction that inserted them), and a second
    query with the opposite sort direction has no guarantee of breaking that tie the same way the
    first one did.
    """
    messages = await list_messages(db, tenant_id=tenant_id, conversation_id=conversation_id)
    recent = messages[-HISTORY_LIMIT:]
    return [{"role": m.role.value, "content": m.content} for m in recent]


async def add_message(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    role: MessageRole,
    content: str,
    citations: list[dict[str, str]] | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> Message:
    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        citations=citations or [],
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )
    db.add(message)
    await db.flush()
    return message
