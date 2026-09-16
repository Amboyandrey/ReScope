"""Chat's own building blocks: retrieval, context rendering, citation resolution, and
conversation/message persistence — the router's own streaming endpoint is tested separately.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.errors import ConversationNotFound
from app.models import Company, CompanyType, Embedding, MessageRole, SourceKind, User
from app.services import chat as chat_module
from app.services import search as search_module
from app.services.catalogue import CatalogueFilters
from app.services.chat import (
    RetrievedItem,
    add_message,
    build_context,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    recent_history_for_prompt,
    resolve_citations,
    retrieve_context,
)
from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers

_DIMENSIONS = 1024


def _vector(hot_index: int) -> list[float]:
    v = [0.0] * _DIMENSIONS
    v[hot_index] = 1.0
    return v


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def _setup(client: AsyncClient, db: AsyncSession) -> tuple[dict[str, str], uuid.UUID, uuid.UUID]:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = uuid.UUID(created.json()["id"])

    await set_tenant_scope(db, tenant_id)
    company = await db.get(Company, company_id)
    assert company is not None
    company.company_type = CompanyType.MANUFACTURER
    company.hq_country = "DE"
    company.hq_city = "Berlin"
    company.overview = "Acme makes widgets."
    source_id = uuid.uuid4()
    db.add(
        Embedding(
            tenant_id=tenant_id,
            company_id=company_id,
            source_kind=SourceKind.OFFERING,
            source_id=source_id,
            content="Widget: a sturdy widget",
            embedding=_vector(0),
            model="test",
        )
    )
    await db.commit()
    return headers, tenant_id, company_id


async def test_retrieve_context_returns_the_closest_rows(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, tenant_id, company_id = await _setup(client, db)
    del headers, company_id
    await set_tenant_scope(db, tenant_id)  # transaction-local — reset after _setup's own commit

    monkeypatch.setattr(search_module, "embed_text", AsyncMock(return_value=_vector(0)))
    monkeypatch.setattr(chat_module, "embed_text", AsyncMock(return_value=_vector(0)))

    items = await retrieve_context(db, tenant_id=tenant_id, query="widgets")
    assert len(items) == 1
    assert items[0].content == "Widget: a sturdy widget"
    assert items[0].source_kind == SourceKind.OFFERING


async def test_retrieve_context_respects_catalogue_filters(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, tenant_id, company_id = await _setup(client, db)
    del headers, company_id
    await set_tenant_scope(db, tenant_id)  # transaction-local — reset after _setup's own commit

    monkeypatch.setattr(chat_module, "embed_text", AsyncMock(return_value=_vector(0)))

    # A country that doesn't match the only company excludes it from retrieval entirely.
    items = await retrieve_context(
        db, tenant_id=tenant_id, query="widgets", filters=CatalogueFilters(country="US")
    )
    assert items == []

    items = await retrieve_context(
        db, tenant_id=tenant_id, query="widgets", filters=CatalogueFilters(country="DE")
    )
    assert len(items) == 1


def test_build_context_includes_facts_overview_and_items() -> None:
    company = Company(
        tenant_id=uuid.uuid4(),
        domain="acme.example",
        name="Acme",
        website_url="https://acme.example",
        created_by=uuid.uuid4(),
        overview="Acme makes widgets.",
        company_type=CompanyType.MANUFACTURER,
        hq_city="Berlin",
        hq_country="DE",
    )
    item = RetrievedItem(
        company=company,
        source_kind=SourceKind.OFFERING,
        source_id=uuid.uuid4(),
        content="Widget: a sturdy widget",
        distance=0.1,
    )
    text = build_context([item])
    assert "### Acme" in text
    assert "Berlin, DE" in text
    assert "Acme makes widgets." in text
    assert "Widget: a sturdy widget" in text


def test_resolve_citations_only_cites_companies_present_in_context() -> None:
    company = Company(
        tenant_id=uuid.uuid4(),
        domain="acme.example",
        name="Acme",
        website_url="https://acme.example",
        created_by=uuid.uuid4(),
    )
    item = RetrievedItem(
        company=company, source_kind=SourceKind.OFFERING, source_id=uuid.uuid4(), content="x", distance=0.1
    )
    citations = resolve_citations("Consider [Acme] and also [Nonexistent Co].", [item])
    assert len(citations) == 1
    assert citations[0]["company_id"] == str(company.id)


def test_resolve_citations_dedupes_repeated_mentions() -> None:
    company = Company(
        tenant_id=uuid.uuid4(),
        domain="acme.example",
        name="Acme",
        website_url="https://acme.example",
        created_by=uuid.uuid4(),
    )
    item = RetrievedItem(
        company=company, source_kind=SourceKind.OFFERING, source_id=uuid.uuid4(), content="x", distance=0.1
    )
    citations = resolve_citations("[Acme] is great. Later, [Acme] again.", [item])
    assert len(citations) == 1


async def test_conversation_crud_is_owner_scoped(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "member@example.com", "role": "member"},
        headers=headers,
    )
    token = invite.json()["token"]
    client.cookies.clear()

    await signup(client, email="member@example.com")
    await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))
    member_headers = tenant_headers(client, tenant["slug"])

    await set_tenant_scope(db, tenant_id)

    owner_id = await db.scalar(select(User.id).where(User.email == "owner@example.com"))
    member_id = await db.scalar(select(User.id).where(User.email == "member@example.com"))
    assert owner_id is not None and member_id is not None

    conversation = await create_conversation(db, tenant_id=tenant_id, owner_id=owner_id, title="  ")
    assert conversation.title == "New chat"
    await db.commit()

    await set_tenant_scope(db, tenant_id)
    owner_conversations = await list_conversations(db, tenant_id=tenant_id, owner_id=owner_id)
    member_conversations = await list_conversations(db, tenant_id=tenant_id, owner_id=member_id)
    assert len(owner_conversations) == 1
    assert member_conversations == []

    with pytest.raises(ConversationNotFound):
        await get_conversation(db, tenant_id=tenant_id, owner_id=member_id, conversation_id=conversation.id)

    del headers, member_headers


async def test_add_message_and_history_ordering(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])

    await set_tenant_scope(db, tenant_id)

    owner_id = await db.scalar(select(User.id).where(User.email == "ada@example.com"))
    assert owner_id is not None
    conversation = await create_conversation(db, tenant_id=tenant_id, owner_id=owner_id, title="Chat")
    await add_message(
        db, tenant_id=tenant_id, conversation_id=conversation.id, role=MessageRole.USER, content="hi"
    )
    await add_message(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content="hello",
        citations=[{"company_id": "x", "source_kind": "offering", "source_id": "y"}],
    )
    await db.commit()

    await set_tenant_scope(db, tenant_id)
    messages = await list_messages(db, tenant_id=tenant_id, conversation_id=conversation.id)
    assert [m.role for m in messages] == [MessageRole.USER, MessageRole.ASSISTANT]

    history = await recent_history_for_prompt(db, tenant_id=tenant_id, conversation_id=conversation.id)
    assert history == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]

    await delete_conversation(db, tenant_id=tenant_id, owner_id=owner_id, conversation_id=conversation.id)
    assert await list_conversations(db, tenant_id=tenant_id, owner_id=owner_id) == []
