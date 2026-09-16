"""Registering, validating, listing, and removing a workspace's own provider credentials — and
what registering one means for quotas and key resolution.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.errors import CredentialNotFound, CredentialValidationFailed, QuotaExceeded
from app.models import Provider, ScrapeMode, Tenant, UsageBilledTo, UsageKind, User
from app.services.credentials import (
    decrypt_credential_key,
    get_active_credential,
    list_credentials,
    remove_credential,
    set_credential,
)
from app.services.llm import has_own_anthropic_key, resolve_anthropic_key
from app.services.quotas import assert_within_quota
from app.services.usage import record_usage_event
from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _mock_anthropic_success(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_create = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(
        anthropic, "AsyncAnthropic", lambda **_: SimpleNamespace(messages=SimpleNamespace(create=mock_create))
    )


def _mock_anthropic_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(401, request=request)
    error = anthropic.APIStatusError("invalid x-api-key", response=response, body=None)
    mock_create = AsyncMock(side_effect=error)
    monkeypatch.setattr(
        anthropic, "AsyncAnthropic", lambda **_: SimpleNamespace(messages=SimpleNamespace(create=mock_create))
    )


def _mock_browser_use(monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={})

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


async def _user_id(db: AsyncSession, email: str = "ada@example.com") -> uuid.UUID:
    """A real user id (`created_by`'s FK target) for whichever account `signup()` just made."""
    user_id = await db.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    return user_id


async def test_set_credential_stores_it_encrypted_and_masked(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_anthropic_success(monkeypatch)
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])

    await set_tenant_scope(db, tenant_id)
    credential = await set_credential(
        db,
        tenant_id=tenant_id,
        created_by=await _user_id(db),
        provider=Provider.ANTHROPIC,
        api_key="sk-ant-abc123",
    )
    assert credential.last4 == "c123"
    assert credential.ciphertext != b"sk-ant-abc123"
    assert decrypt_credential_key(credential) == "sk-ant-abc123"


async def test_set_credential_rejects_an_invalid_anthropic_key(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_anthropic_rejects(monkeypatch)
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])

    await set_tenant_scope(db, tenant_id)
    with pytest.raises(CredentialValidationFailed):
        await set_credential(
            db,
            tenant_id=tenant_id,
            created_by=await _user_id(db),
            provider=Provider.ANTHROPIC,
            api_key="sk-ant-bad",
        )
    assert await get_active_credential(db, tenant_id=tenant_id, provider=Provider.ANTHROPIC) is None


async def test_set_credential_validates_browser_use_key(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)

    _mock_browser_use(monkeypatch, 401)
    with pytest.raises(CredentialValidationFailed):
        await set_credential(
            db,
            tenant_id=tenant_id,
            created_by=await _user_id(db),
            provider=Provider.BROWSER_USE,
            api_key="bu-bad",
        )

    _mock_browser_use(monkeypatch, 200)
    credential = await set_credential(
        db,
        tenant_id=tenant_id,
        created_by=await _user_id(db),
        provider=Provider.BROWSER_USE,
        api_key="bu-good",
    )
    assert credential.provider == Provider.BROWSER_USE


async def test_setting_a_second_key_for_the_same_provider_replaces_it(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_anthropic_success(monkeypatch)
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)

    created_by = await _user_id(db)
    first = await set_credential(
        db, tenant_id=tenant_id, created_by=created_by, provider=Provider.ANTHROPIC, api_key="sk-ant-first1"
    )
    second = await set_credential(
        db, tenant_id=tenant_id, created_by=created_by, provider=Provider.ANTHROPIC, api_key="sk-ant-second2"
    )
    assert first.id == second.id
    assert second.last4 == "ond2"
    all_credentials = await list_credentials(db, tenant_id=tenant_id)
    assert len(all_credentials) == 1


async def test_remove_credential(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_anthropic_success(monkeypatch)
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)

    await set_credential(
        db,
        tenant_id=tenant_id,
        created_by=await _user_id(db),
        provider=Provider.ANTHROPIC,
        api_key="sk-ant-abc123",
    )
    await remove_credential(db, tenant_id=tenant_id, provider=Provider.ANTHROPIC)
    assert await get_active_credential(db, tenant_id=tenant_id, provider=Provider.ANTHROPIC) is None

    with pytest.raises(CredentialNotFound):
        await remove_credential(db, tenant_id=tenant_id, provider=Provider.ANTHROPIC)


async def test_resolve_anthropic_key_prefers_the_tenants_own(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_anthropic_success(monkeypatch)
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)

    platform_default = await resolve_anthropic_key(db, tenant_id=tenant_id)
    assert platform_default.billed_to == UsageBilledTo.PLATFORM
    assert not await has_own_anthropic_key(db, tenant_id=tenant_id)

    await set_credential(
        db,
        tenant_id=tenant_id,
        created_by=await _user_id(db),
        provider=Provider.ANTHROPIC,
        api_key="sk-ant-abc123",
    )
    resolved = await resolve_anthropic_key(db, tenant_id=tenant_id)
    assert resolved.billed_to == UsageBilledTo.TENANT
    assert resolved.api_key == "sk-ant-abc123"
    assert await has_own_anthropic_key(db, tenant_id=tenant_id)


async def test_byok_tenant_is_exempt_from_the_quota(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_anthropic_success(monkeypatch)

    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)

    await signup(client)
    tenant_data = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant_data["id"])
    headers = tenant_headers(client, tenant_data["slug"])

    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]
    jobs_resp = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs", headers=headers
    )
    job_id = uuid.UUID(jobs_resp.json()[0]["id"])

    await set_tenant_scope(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None

    # Free plan's profiles_per_month is 10 (migration 0002) — fill it with fake usage.
    for _ in range(10):
        await record_usage_event(
            db,
            tenant_id=tenant_id,
            job_id=job_id,
            kind=UsageKind.PROFILE,
            model="claude-sonnet-5",
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.01,
        )
    await db.commit()
    await set_tenant_scope(db, tenant_id)

    with pytest.raises(QuotaExceeded):
        await assert_within_quota(db, tenant=tenant, mode=ScrapeMode.FAST)

    await set_credential(
        db,
        tenant_id=tenant_id,
        created_by=await _user_id(db),
        provider=Provider.ANTHROPIC,
        api_key="sk-ant-abc123",
    )
    # No QuotaExceeded despite the same exhausted usage, since this tenant now runs on its own key.
    await assert_within_quota(db, tenant=tenant, mode=ScrapeMode.FAST)
    await assert_within_quota(db, tenant=tenant, mode=ScrapeMode.DEEP)


async def test_credentials_router_requires_admin(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
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

    response = await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "anthropic", "api_key": "sk-ant-abc123"},
        headers=tenant_headers(client, tenant["slug"]),
    )
    assert response.status_code == 403


async def test_credentials_router_set_list_delete(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_anthropic_success(monkeypatch)
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    created = await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "anthropic", "api_key": "sk-ant-abc123"},
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["last4"] == "c123"
    assert "api_key" not in body

    listed = await client.get("/api/v1/tenants/current/credentials", headers=headers)
    assert [c["provider"] for c in listed.json()] == ["anthropic"]

    deleted = await client.delete("/api/v1/tenants/current/credentials/anthropic", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/tenants/current/credentials", headers=headers)).json() == []
