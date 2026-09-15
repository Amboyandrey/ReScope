"""The platform-operator area — gated by is_superadmin, never by tenant membership."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from tests.helpers import create_tenant, csrf_headers, signup, tenant_headers


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def _make_superadmin(db: AsyncSession, email: str) -> None:
    user = await db.scalar(select(User).where(User.email == email))
    assert user is not None
    user.is_superadmin = True
    await db.commit()


async def test_admin_routes_reject_a_regular_user(client: AsyncClient) -> None:
    await signup(client)
    response = await client.get("/api/v1/admin/tenants")
    assert response.status_code == 403


async def test_admin_routes_require_a_session_at_all(client: AsyncClient) -> None:
    response = await client.get("/api/v1/admin/tenants")
    assert response.status_code == 401


async def test_superadmin_can_list_every_tenant_and_its_spend(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client, email="owner-a@example.com")
    await create_tenant(client, name="Tenant A")
    client.cookies.clear()

    await signup(client, email="owner-b@example.com")
    await create_tenant(client, name="Tenant B")
    await _make_superadmin(db, "owner-b@example.com")

    response = await client.get("/api/v1/admin/tenants")
    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert {"Tenant A", "Tenant B"} <= names
    tenant_b = next(t for t in response.json() if t["name"] == "Tenant B")
    assert tenant_b["plan_name"] == "Free"
    assert tenant_b["member_count"] == 1
    assert tenant_b["spend_this_month_usd"] == 0


async def test_superadmin_can_change_a_tenants_plan(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    await _make_superadmin(db, "owner@example.com")

    response = await client.patch(
        f"/api/v1/admin/tenants/{tenant['id']}/plan", json={"plan_id": "pro"}, headers=csrf_headers(client)
    )
    assert response.status_code == 200
    assert response.json()["plan_id"] == "pro"
    assert response.json()["plan_name"] == "Pro"


async def test_changing_to_an_unknown_plan_404s(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    await _make_superadmin(db, "owner@example.com")

    response = await client.patch(
        f"/api/v1/admin/tenants/{tenant['id']}/plan",
        json={"plan_id": "does-not-exist"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 404


async def test_superadmin_can_toggle_the_killswitch(client: AsyncClient, db: AsyncSession) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    await _make_superadmin(db, "owner@example.com")
    headers = tenant_headers(client, tenant["slug"])

    initial = await client.get("/api/v1/admin/settings")
    assert initial.json()["scraping_paused"] is False

    paused = await client.patch(
        "/api/v1/admin/settings", json={"scraping_paused": True}, headers=csrf_headers(client)
    )
    assert paused.status_code == 200
    assert paused.json()["scraping_paused"] is True

    blocked = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    assert blocked.status_code == 503

    await client.patch(
        "/api/v1/admin/settings", json={"scraping_paused": False}, headers=csrf_headers(client)
    )
