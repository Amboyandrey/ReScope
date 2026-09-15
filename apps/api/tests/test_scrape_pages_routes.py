"""Listing a job's pages and serving a Tier 2 screenshot back."""

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.storage import save_screenshot
from app.models import ScrapeJob, ScrapePage
from tests.helpers import create_tenant, signup, tenant_headers


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def _setup(
    client: AsyncClient, db: AsyncSession
) -> tuple[dict[str, str], uuid.UUID, str, uuid.UUID, ScrapePage]:
    """Sign up, create a tenant and a company, and add one bare (screenshot-less) scrape page."""
    await signup(client)
    tenant = (await create_tenant(client)).json()
    tenant_id = uuid.UUID(tenant["id"])
    headers = tenant_headers(client, tenant["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]

    await set_tenant_scope(db, tenant_id)
    job_id = await db.scalar(select(ScrapeJob.id).where(ScrapeJob.company_id == uuid.UUID(company_id)))
    assert job_id is not None

    page = ScrapePage(
        tenant_id=tenant_id,
        job_id=job_id,
        url="https://example.com/tab-2",
        status_code=None,
        content_hash="abc",
        markdown="revealed content",
    )
    db.add(page)
    await db.flush()
    await db.commit()
    return headers, tenant_id, company_id, job_id, page


async def test_list_pages_reports_which_have_a_screenshot(client: AsyncClient, db: AsyncSession) -> None:
    headers, tenant_id, company_id, job_id, page = await _setup(client, db)

    await set_tenant_scope(db, tenant_id)
    page_db = await db.get(ScrapePage, page.id)
    assert page_db is not None
    page_db.screenshot_key = "some/key.png"
    await db.commit()

    response = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs/{job_id}/pages", headers=headers
    )
    assert response.status_code == 200
    [item] = response.json()
    assert item["has_screenshot"] is True
    assert item["url"] == "https://example.com/tab-2"


async def test_screenshot_endpoint_streams_the_stored_bytes(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from app.core import storage as storage_module

    monkeypatch.setattr(storage_module.settings, "storage_dir", str(tmp_path))
    headers, tenant_id, company_id, job_id, page = await _setup(client, db)

    key = save_screenshot(tenant_id, job_id, b"fake-png-data")
    await set_tenant_scope(db, tenant_id)
    page_db = await db.get(ScrapePage, page.id)
    assert page_db is not None
    page_db.screenshot_key = key
    await db.commit()

    response = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs/{job_id}/pages/{page.id}/screenshot",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.content == b"fake-png-data"
    assert response.headers["content-type"] == "image/png"


async def test_screenshot_404s_when_the_page_has_none(client: AsyncClient, db: AsyncSession) -> None:
    headers, _tenant_id, company_id, job_id, page = await _setup(client, db)
    response = await client.get(
        f"/api/v1/tenants/current/companies/{company_id}/scrape-jobs/{job_id}/pages/{page.id}/screenshot",
        headers=headers,
    )
    assert response.status_code == 404
