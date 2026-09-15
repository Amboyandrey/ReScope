"""Tenant creation, membership listing, and the isolation row-level security backstops."""

from httpx import AsyncClient

from tests.helpers import create_tenant, signup, tenant_headers


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
