"""Registering, validating, listing, and removing a workspace's own provider credentials — and
what registering one means for quotas and key resolution.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import openai
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
    validate_chat_model,
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


def _mock_openai_compatible_models_list(monkeypatch: pytest.MonkeyPatch, *, ok: bool) -> None:
    async def list_impl() -> object:
        if not ok:
            request = httpx.Request("GET", "https://api.openai.com/v1/models")
            response = httpx.Response(401, request=request)
            raise openai.APIStatusError("invalid api key", response=response, body=None)
        return SimpleNamespace()

    monkeypatch.setattr(
        openai, "AsyncOpenAI", lambda **_: SimpleNamespace(models=SimpleNamespace(list=list_impl))
    )


def _mock_openai_compatible_chat_create(monkeypatch: pytest.MonkeyPatch, *, ok: bool) -> None:
    async def create_impl(**_: object) -> object:
        if not ok:
            request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            response = httpx.Response(404, request=request)
            raise openai.APIStatusError("model not found", response=response, body=None)
        return SimpleNamespace()

    monkeypatch.setattr(
        openai,
        "AsyncOpenAI",
        lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create_impl))),
    )


def _mock_http_status(monkeypatch: pytest.MonkeyPatch, status_code: int) -> None:
    """Any real HTTP response, regardless of status — what `_validate_custom_endpoint` treats as
    "a server answered there"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={})

    real_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


def _mock_http_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    real_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


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


@pytest.mark.parametrize("provider", [Provider.OPENAI, Provider.GEMINI, Provider.NEBIUS])
async def test_set_credential_validates_openai_compatible_providers(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, provider: Provider
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)

    _mock_openai_compatible_models_list(monkeypatch, ok=False)
    with pytest.raises(CredentialValidationFailed):
        await set_credential(
            db, tenant_id=tenant_id, created_by=await _user_id(db), provider=provider, api_key="bad-key"
        )

    _mock_openai_compatible_models_list(monkeypatch, ok=True)
    credential = await set_credential(
        db, tenant_id=tenant_id, created_by=await _user_id(db), provider=provider, api_key="good-key"
    )
    assert credential.provider == provider


async def test_set_credential_requires_a_base_url_for_the_custom_provider(
    client: AsyncClient, db: AsyncSession
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)

    with pytest.raises(CredentialValidationFailed):
        await set_credential(
            db, tenant_id=tenant_id, created_by=await _user_id(db), provider=Provider.CUSTOM, api_key="key"
        )


async def test_set_credential_rejects_an_unreachable_custom_endpoint(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)

    _mock_http_unreachable(monkeypatch)
    with pytest.raises(CredentialValidationFailed):
        await set_credential(
            db,
            tenant_id=tenant_id,
            created_by=await _user_id(db),
            provider=Provider.CUSTOM,
            api_key="key",
            base_url="https://unreachable.example.com/v1",
        )


async def test_set_credential_accepts_a_reachable_custom_endpoint_even_if_it_401s(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    await set_tenant_scope(db, tenant_id)

    _mock_http_status(monkeypatch, 401)
    credential = await set_credential(
        db,
        tenant_id=tenant_id,
        created_by=await _user_id(db),
        provider=Provider.CUSTOM,
        api_key="key",
        base_url="https://my-server.example.com/v1",
    )
    assert credential.provider == Provider.CUSTOM
    assert credential.base_url == "https://my-server.example.com/v1"


async def test_validate_chat_model_for_custom_provider_uses_the_given_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    class _FakeOpenAI:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            captured["base_url"] = base_url
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        async def _create(self, **_: object) -> object:
            return SimpleNamespace()

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeOpenAI)
    await validate_chat_model(Provider.CUSTOM, "key", "my-model", base_url="https://my-server.example.com/v1")
    assert captured["base_url"] == "https://my-server.example.com/v1"


async def test_validate_chat_model_surfaces_anthropics_own_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_anthropic_rejects(monkeypatch)
    with pytest.raises(CredentialValidationFailed):
        await validate_chat_model(Provider.ANTHROPIC, "sk-ant-bad", "claude-sonnet-5")


async def test_validate_chat_model_accepts_a_working_anthropic_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_anthropic_success(monkeypatch)
    await validate_chat_model(Provider.ANTHROPIC, "sk-ant-good", "claude-sonnet-5")


@pytest.mark.parametrize("provider", [Provider.OPENAI, Provider.GEMINI, Provider.NEBIUS])
async def test_validate_chat_model_surfaces_an_openai_compatible_rejection(
    monkeypatch: pytest.MonkeyPatch, provider: Provider
) -> None:
    _mock_openai_compatible_chat_create(monkeypatch, ok=False)
    with pytest.raises(CredentialValidationFailed):
        await validate_chat_model(provider, "key", "bogus-model")


@pytest.mark.parametrize("provider", [Provider.OPENAI, Provider.GEMINI, Provider.NEBIUS])
async def test_validate_chat_model_accepts_a_working_openai_compatible_model(
    monkeypatch: pytest.MonkeyPatch, provider: Provider
) -> None:
    _mock_openai_compatible_chat_create(monkeypatch, ok=True)
    await validate_chat_model(provider, "key", "a-real-model")


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


async def test_credentials_router_rejects_a_base_url_on_a_non_custom_provider(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    response = await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "anthropic", "api_key": "sk-ant-abc123", "base_url": "https://example.com/v1"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_credentials_router_requires_a_base_url_for_custom(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    response = await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "custom", "api_key": "key"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_credentials_router_sets_a_custom_provider_with_its_base_url(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_http_status(monkeypatch, 200)
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    response = await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "custom", "api_key": "key", "base_url": "https://my-server.example.com/v1"},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["base_url"] == "https://my-server.example.com/v1"
