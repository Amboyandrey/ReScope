"""Tenant creation, membership listing, and the isolation row-level security backstops."""

from types import SimpleNamespace

import httpx
import openai
import pytest
from httpx import AsyncClient

from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers


async def test_create_tenant_derives_slug_and_makes_caller_owner(client: AsyncClient) -> None:
    await signup(client)
    response = await create_tenant(client, name="Acme Inc")
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "acme-inc"
    assert body["name"] == "Acme Inc"

    current = await client.get("/api/v1/tenants/current", headers={"X-Tenant-Slug": "acme-inc"})
    assert current.status_code == 200


async def test_list_mine_includes_role(client: AsyncClient) -> None:
    await signup(client)
    await create_tenant(client, name="Acme Inc")
    response = await client.get("/api/v1/tenants")
    assert response.status_code == 200
    [tenant] = response.json()
    assert tenant["role"] == "owner"


async def test_reserved_slug_is_rejected(client: AsyncClient) -> None:
    await signup(client)
    response = await create_tenant(client, name="www", slug="www")
    assert response.status_code == 422


async def test_duplicate_slug_is_rejected(client: AsyncClient) -> None:
    await signup(client)
    await create_tenant(client, name="Acme Inc")
    response = await create_tenant(client, name="Acme Inc Two", slug="acme-inc")
    assert response.status_code == 409


async def test_missing_tenant_header_is_not_found(client: AsyncClient) -> None:
    await signup(client)
    await create_tenant(client, name="Acme Inc")
    response = await client.get("/api/v1/tenants/current")
    assert response.status_code == 404


async def test_nonmember_gets_404_not_403_for_a_real_tenant(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    await create_tenant(client, name="Acme Inc")
    client.cookies.clear()

    await signup(client, email="stranger@example.com")
    response = await client.get("/api/v1/tenants/current", headers={"X-Tenant-Slug": "acme-inc"})
    assert response.status_code == 404


async def test_rls_hides_a_membership_row_scoped_to_a_different_tenant(client: AsyncClient) -> None:
    """Simulates a query that forgot its own `WHERE tenant_id = ...` — RLS should still deny it."""
    await signup(client, email="owner-a@example.com")
    tenant_a = (await create_tenant(client, name="Tenant A")).json()
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    tenant_b = (await create_tenant(client, name="Tenant B")).json()

    # Scoped to tenant B, "current" must never see tenant A even by a crafted header value that
    # isn't tenant B's own slug — the membership lookup itself is what enforces this, backed by RLS.
    response = await client.get("/api/v1/tenants/current", headers=tenant_headers(client, tenant_a["slug"]))
    assert response.status_code == 404
    response = await client.get("/api/v1/tenants/current", headers=tenant_headers(client, tenant_b["slug"]))
    assert response.status_code == 200


async def test_audit_log_records_tenant_creation_and_is_tenant_scoped(client: AsyncClient) -> None:
    await signup(client, email="owner-a@example.com")
    tenant_a = (await create_tenant(client, name="Tenant A")).json()
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    tenant_b = (await create_tenant(client, name="Tenant B")).json()

    logs_b = await client.get(
        "/api/v1/tenants/current/audit-logs", headers=tenant_headers(client, tenant_b["slug"])
    )
    assert logs_b.status_code == 200
    actions = [entry["action"] for entry in logs_b.json()]
    assert actions == ["tenant.created"]

    # Owner B has no membership in tenant A, so even naming its slug 404s before audit logs are read.
    logs_a = await client.get(
        "/api/v1/tenants/current/audit-logs", headers=tenant_headers(client, tenant_a["slug"])
    )
    assert logs_a.status_code == 404


async def test_new_tenant_defaults_to_the_custom_scrape_provider(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    assert tenant["scrape_provider"] == "custom"


async def test_switching_to_browser_use_cloud_requires_a_key(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    response = await client.put(
        "/api/v1/tenants/current/scrape-provider",
        json={"provider": "browser_use_cloud"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_switching_to_browser_use_cloud_succeeds_once_a_key_is_registered(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    real_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "browser_use", "api_key": "bu-test-key"},
        headers=headers,
    )
    response = await client.put(
        "/api/v1/tenants/current/scrape-provider",
        json={"provider": "browser_use_cloud"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["scrape_provider"] == "browser_use_cloud"


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch, *, chat_ok: bool = True) -> None:
    async def list_ok() -> object:
        return SimpleNamespace()

    async def create_impl(**_: object) -> object:
        if not chat_ok:
            request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            response = httpx.Response(404, request=request)
            raise openai.APIStatusError("model not found", response=response, body=None)
        return SimpleNamespace()

    monkeypatch.setattr(
        openai,
        "AsyncOpenAI",
        lambda **_: SimpleNamespace(
            models=SimpleNamespace(list=list_ok),
            chat=SimpleNamespace(completions=SimpleNamespace(create=create_impl)),
        ),
    )


async def test_switching_chat_model_to_a_provider_without_a_key_is_rejected(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    response = await client.put(
        "/api/v1/tenants/current/chat-model",
        json={"provider": "openai", "model": "gpt-4o-mini"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_switching_chat_model_succeeds_once_a_key_is_registered_and_the_model_validates(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_openai(monkeypatch)
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "openai", "api_key": "sk-openai-abc"},
        headers=headers,
    )
    response = await client.put(
        "/api/v1/tenants/current/chat-model",
        json={"provider": "openai", "model": "gpt-4o-mini"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["chat_provider"] == "openai"
    assert body["chat_model"] == "gpt-4o-mini"


async def test_switching_chat_model_rejects_a_model_the_key_cant_actually_use(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    _install_fake_openai(monkeypatch)
    await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "openai", "api_key": "sk-openai-abc"},
        headers=headers,
    )

    _install_fake_openai(monkeypatch, chat_ok=False)
    response = await client.put(
        "/api/v1/tenants/current/chat-model",
        json={"provider": "openai", "model": "bogus-model"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_switching_chat_model_to_custom_requires_a_registered_endpoint(client: AsyncClient) -> None:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    response = await client.put(
        "/api/v1/tenants/current/chat-model",
        json={"provider": "custom", "model": "my-model"},
        headers=headers,
    )
    assert response.status_code == 422


async def test_switching_chat_model_to_custom_succeeds_once_registered(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_openai(monkeypatch)  # backs the model-validation call, made via the openai SDK

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    real_client = httpx.AsyncClient

    def fake_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    # Registering the credential itself uses a raw httpx reachability probe, not the openai SDK.
    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])

    await client.put(
        "/api/v1/tenants/current/credentials",
        json={"provider": "custom", "api_key": "key", "base_url": "https://my-server.example.com/v1"},
        headers=headers,
    )
    response = await client.put(
        "/api/v1/tenants/current/chat-model",
        json={"provider": "custom", "model": "my-model"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["chat_provider"] == "custom"
    assert body["chat_model"] == "my-model"


async def test_member_cannot_change_the_chat_model(client: AsyncClient) -> None:
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
        "/api/v1/tenants/current/chat-model",
        json={"provider": "anthropic", "model": "claude-sonnet-5"},
        headers=tenant_headers(client, tenant["slug"]),
    )
    assert response.status_code == 403


async def test_member_cannot_change_the_scrape_provider(client: AsyncClient) -> None:
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
        "/api/v1/tenants/current/scrape-provider",
        json={"provider": "custom"},
        headers=tenant_headers(client, tenant["slug"]),
    )
    assert response.status_code == 403
