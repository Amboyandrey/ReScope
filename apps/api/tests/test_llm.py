"""The chat provider seam (docs/PLAN.md §18): the OpenAI-compatible adapter's own streaming and
usage-capture behavior, factory dispatch, and resolving which key/model/provider a tenant's chat
messages actually run on.
"""

import uuid
from types import SimpleNamespace

import httpx
import openai
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.errors import CredentialNotFound
from app.llm import OPENAI_COMPATIBLE_BASE_URLS, build_chat_provider
from app.llm.anthropic_chat import AnthropicChat
from app.llm.openai_compatible_chat import OpenAICompatibleChat
from app.models import Provider, Tenant, UsageBilledTo, User
from app.services.credentials import set_credential
from app.services.llm import has_own_chat_key, resolve_chat_model
from tests.helpers import create_tenant, signup


async def _user_id(db: AsyncSession, email: str = "ada@example.com") -> uuid.UUID:
    user_id = await db.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    return user_id


def _install_fake_openai_stream(
    monkeypatch: pytest.MonkeyPatch, chunks: list[tuple[str | None, tuple[int, int] | None]]
) -> None:
    """Each chunk is (content, usage) — `usage` set only on the provider's final chunk, matching
    how `stream_options={"include_usage": True}` actually reports it."""

    async def gen():  # noqa: ANN202
        for content, usage in chunks:
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=content))] if content else [],
                usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]) if usage else None,
            )

    async def fake_create(**_: object) -> object:
        return gen()

    monkeypatch.setattr(
        openai,
        "AsyncOpenAI",
        lambda **_: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
    )


async def test_openai_compatible_chat_streams_text_and_captures_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai_stream(monkeypatch, [("Hello ", None), ("world.", None), (None, (12, 5))])
    provider = OpenAICompatibleChat("key", base_url="https://example.test/v1")
    text = "".join(
        [
            chunk
            async for chunk in provider.stream_text(
                system="sys", messages=[{"role": "user", "content": "hi"}], model="gpt-x", max_tokens=10
            )
        ]
    )
    assert text == "Hello world."
    assert provider.usage is not None
    assert provider.usage.tokens_in == 12
    assert provider.usage.tokens_out == 5


async def test_openai_compatible_chat_usage_is_none_when_never_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_openai_stream(monkeypatch, [("Hi.", None)])
    provider = OpenAICompatibleChat("key", base_url="https://example.test/v1")
    async for _ in provider.stream_text(
        system="sys", messages=[{"role": "user", "content": "hi"}], model="gpt-x", max_tokens=10
    ):
        pass
    assert provider.usage is None


def test_factory_dispatches_anthropic_to_its_own_adapter() -> None:
    assert isinstance(build_chat_provider(Provider.ANTHROPIC, "sk-ant-x"), AnthropicChat)


@pytest.mark.parametrize("provider", [Provider.OPENAI, Provider.GEMINI, Provider.NEBIUS])
def test_factory_dispatches_openai_compatible_providers_with_the_right_base_url(provider: Provider) -> None:
    chat = build_chat_provider(provider, "key")
    assert isinstance(chat, OpenAICompatibleChat)
    assert OPENAI_COMPATIBLE_BASE_URLS[provider]  # every one of these providers has a base URL


def test_factory_requires_a_base_url_for_the_custom_provider() -> None:
    with pytest.raises(ValueError, match="base_url"):
        build_chat_provider(Provider.CUSTOM, "key")


def test_factory_dispatches_custom_to_the_workspaces_own_base_url() -> None:
    chat = build_chat_provider(Provider.CUSTOM, "key", base_url="https://my-server.example.com/v1")
    assert isinstance(chat, OpenAICompatibleChat)
    assert str(chat._client.base_url).startswith("https://my-server.example.com/v1")  # noqa: SLF001


async def test_resolve_chat_model_defaults_to_the_platforms_anthropic_key(
    client: AsyncClient, db: AsyncSession
) -> None:
    await signup(client)
    tenant_data = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant_data["id"])
    await set_tenant_scope(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None

    resolved = await resolve_chat_model(db, tenant=tenant)
    assert resolved.provider == Provider.ANTHROPIC
    assert resolved.model == "claude-sonnet-5"
    assert resolved.billed_to == UsageBilledTo.PLATFORM
    assert not await has_own_chat_key(db, tenant=tenant)


async def test_resolve_chat_model_uses_the_tenants_own_key_for_a_configured_provider(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _ok() -> object:
        return SimpleNamespace()

    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_: SimpleNamespace(models=SimpleNamespace(list=_ok)))

    await signup(client)
    tenant_data = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant_data["id"])
    await set_tenant_scope(db, tenant_id)
    await set_credential(
        db,
        tenant_id=tenant_id,
        created_by=await _user_id(db),
        provider=Provider.OPENAI,
        api_key="sk-openai-abc",
    )
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None
    tenant.settings = {**tenant.settings, "chat": {"provider": "openai", "model": "gpt-4o-mini"}}
    await db.commit()
    await set_tenant_scope(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None

    resolved = await resolve_chat_model(db, tenant=tenant)
    assert resolved.provider == Provider.OPENAI
    assert resolved.model == "gpt-4o-mini"
    assert resolved.api_key == "sk-openai-abc"
    assert resolved.billed_to == UsageBilledTo.TENANT
    assert await has_own_chat_key(db, tenant=tenant)


async def test_resolve_chat_model_carries_the_base_url_for_a_custom_provider(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    real_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    await signup(client)
    tenant_data = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant_data["id"])
    await set_tenant_scope(db, tenant_id)
    await set_credential(
        db,
        tenant_id=tenant_id,
        created_by=await _user_id(db),
        provider=Provider.CUSTOM,
        api_key="sk-custom-abc",
        base_url="https://my-server.example.com/v1",
    )
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None
    tenant.settings = {**tenant.settings, "chat": {"provider": "custom", "model": "my-model"}}
    await db.commit()
    await set_tenant_scope(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None

    resolved = await resolve_chat_model(db, tenant=tenant)
    assert resolved.provider == Provider.CUSTOM
    assert resolved.api_key == "sk-custom-abc"
    assert resolved.base_url == "https://my-server.example.com/v1"
    assert resolved.billed_to == UsageBilledTo.TENANT


async def test_resolve_chat_model_raises_when_the_configured_provider_has_no_key(
    client: AsyncClient, db: AsyncSession
) -> None:
    await signup(client)
    tenant_data = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant_data["id"])
    await set_tenant_scope(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None
    # Written directly rather than through `set_chat_model`, whose own validation would refuse
    # this — isolates `resolve_chat_model`'s own defensive check on stored settings.
    tenant.settings = {**tenant.settings, "chat": {"provider": "gemini", "model": "gemini-2.0-flash"}}
    await db.commit()
    await set_tenant_scope(db, tenant_id)
    tenant = await db.get(Tenant, tenant_id)
    assert tenant is not None

    with pytest.raises(CredentialNotFound):
        await resolve_chat_model(db, tenant=tenant)


async def test_chat_model_response_fields_default_before_any_provider_is_chosen(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    assert tenant["chat_provider"] == "anthropic"
    assert tenant["chat_model"] == "claude-sonnet-5"
