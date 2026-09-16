"""The chat HTTP surface: conversation CRUD, and the streaming send-message endpoint against a
fake Anthropic client (no real key, no real network)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.models import Company, Embedding, SourceKind, UsageEvent, UsageKind
from app.services import chat as chat_module
from app.services.usage import record_usage_event
from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers

_DIMENSIONS = 1024


def _vector(hot_index: int) -> list[float]:
    v = [0.0] * _DIMENSIONS
    v[hot_index] = 1.0
    return v


class _FakeStreamManager:
    def __init__(self, chunks: list[str], tokens_in: int, tokens_out: int) -> None:
        self._chunks = chunks
        self._final = SimpleNamespace(usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out))

    async def __aenter__(self) -> "_FakeStreamManager":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    @property
    def text_stream(self):  # noqa: ANN201 — an async generator, not a plain return type
        async def gen():  # noqa: ANN202
            for chunk in self._chunks:
                yield chunk

        return gen()

    async def get_final_message(self) -> SimpleNamespace:
        return self._final


def _install_fake_anthropic_stream(
    monkeypatch: pytest.MonkeyPatch, chunks: list[str], *, tokens_in: int = 42, tokens_out: int = 17
) -> None:
    def fake_stream(**_: object) -> _FakeStreamManager:
        return _FakeStreamManager(chunks, tokens_in, tokens_out)

    monkeypatch.setattr(
        anthropic,
        "AsyncAnthropic",
        lambda **_: SimpleNamespace(messages=SimpleNamespace(stream=fake_stream)),
    )


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def _setup(client: AsyncClient, db: AsyncSession) -> tuple[dict[str, str], uuid.UUID]:
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
    company.name = "Acme"
    company.overview = "Acme makes widgets."
    db.add(
        Embedding(
            tenant_id=tenant_id,
            company_id=company_id,
            source_kind=SourceKind.OFFERING,
            source_id=uuid.uuid4(),
            content="Widget: a sturdy widget",
            embedding=_vector(0),
            model="test",
        )
    )
    await db.commit()
    return headers, tenant_id


async def test_conversation_crud(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    created = await client.post(
        "/api/v1/tenants/current/conversations", json={"title": "My chat"}, headers=headers
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    listed = await client.get("/api/v1/tenants/current/conversations", headers=headers)
    assert [c["title"] for c in listed.json()] == ["My chat"]

    deleted = await client.delete(f"/api/v1/tenants/current/conversations/{conversation_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/tenants/current/conversations", headers=headers)).json() == []


async def test_a_members_conversation_is_invisible_to_another_member(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    await client.post(
        "/api/v1/tenants/current/conversations", json={"title": "Owner's chat"}, headers=headers
    )

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "member@example.com", "role": "member"},
        headers=headers,
    )
    token = invite.json()["token"]
    client.cookies.clear()
    await signup(client, email="member@example.com")
    await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))

    listed = await client.get(
        "/api/v1/tenants/current/conversations", headers=tenant_headers(client, tenant["slug"])
    )
    assert listed.json() == []


async def test_send_message_streams_and_persists_both_turns(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, tenant_id = await _setup(client, db)
    monkeypatch.setattr(chat_module, "embed_text", AsyncMock(return_value=_vector(0)))
    _install_fake_anthropic_stream(monkeypatch, ["Acme makes widgets. ", "See [Acme]."])

    created = await client.post("/api/v1/tenants/current/conversations", json={}, headers=headers)
    conversation_id = created.json()["id"]

    response = await client.post(
        f"/api/v1/tenants/current/conversations/{conversation_id}/messages",
        json={"content": "What does Acme make?"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.text
    assert "Acme makes widgets." in body
    assert "event: citations" in body
    assert "event: done" in body

    messages_resp = await client.get(
        f"/api/v1/tenants/current/conversations/{conversation_id}/messages", headers=headers
    )
    messages = messages_resp.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "What does Acme make?"
    assert "Acme makes widgets." in messages[1]["content"]
    assert len(messages[1]["citations"]) == 1

    await set_tenant_scope(db, tenant_id)
    events = list((await db.scalars(select(UsageEvent).where(UsageEvent.tenant_id == tenant_id))).all())
    chat_events = [e for e in events if e.kind == UsageKind.CHAT]
    assert len(chat_events) == 1
    assert chat_events[0].job_id is None
    assert chat_events[0].tokens_in == 42
    assert chat_events[0].tokens_out == 17


async def test_send_message_to_someone_elses_conversation_404s(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, _tenant_id = await _setup(client, db)
    del headers
    monkeypatch.setattr(chat_module, "embed_text", AsyncMock(return_value=_vector(0)))

    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client, name="Tenant Two")).json()
    owner_headers = tenant_headers(client, tenant["slug"])
    created = await client.post("/api/v1/tenants/current/conversations", json={}, headers=owner_headers)
    conversation_id = created.json()["id"]

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "member@example.com", "role": "member"},
        headers=owner_headers,
    )
    token = invite.json()["token"]
    client.cookies.clear()
    await signup(client, email="member@example.com")
    await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))
    member_headers = tenant_headers(client, tenant["slug"])

    response = await client.post(
        f"/api/v1/tenants/current/conversations/{conversation_id}/messages",
        json={"content": "hi"},
        headers=member_headers,
    )
    assert response.status_code == 404


async def test_send_message_is_rejected_once_the_chat_quota_is_used_up(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers, tenant_id = await _setup(client, db)
    monkeypatch.setattr(chat_module, "embed_text", AsyncMock(return_value=_vector(0)))

    created = await client.post("/api/v1/tenants/current/conversations", json={}, headers=headers)
    conversation_id = created.json()["id"]

    # Free plan's chat_messages_per_month is 100 (migration 0012) — fill it with fake usage.
    await set_tenant_scope(db, tenant_id)
    for _ in range(100):
        await record_usage_event(
            db,
            tenant_id=tenant_id,
            job_id=None,
            kind=UsageKind.CHAT,
            model="claude-sonnet-5",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.01,
        )
    await db.commit()

    response = await client.post(
        f"/api/v1/tenants/current/conversations/{conversation_id}/messages",
        json={"content": "hi"},
        headers=headers,
    )
    assert response.status_code == 402
