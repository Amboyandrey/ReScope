"""CSV contact import — column matching, partial-row failures, and permissions."""

import io
import uuid

import pytest
from httpx import AsyncClient

from tests.helpers import create_tenant, signup, tenant_headers


@pytest.fixture(autouse=True)
def _stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop_enqueue(*, job_id: uuid.UUID, tenant_id: uuid.UUID, company_id: uuid.UUID) -> None:
        del job_id, tenant_id, company_id

    monkeypatch.setattr("app.routers.v1.companies.enqueue_scrape_job", _noop_enqueue)


async def _setup_company(client: AsyncClient) -> tuple[dict[str, str], str]:
    await signup(client)
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    return headers, created.json()["id"]


_UploadFiles = dict[str, tuple[str, io.BytesIO, str]]


def _upload(headers: dict[str, str], csv_text: str) -> tuple[dict[str, str], _UploadFiles]:
    return headers, {"file": ("contacts.csv", io.BytesIO(csv_text.encode()), "text/csv")}


async def test_import_matches_common_column_aliases(client: AsyncClient) -> None:
    headers, company_id = await _setup_company(client)
    csv_text = (
        "First Name,Last Name,Email Address,Job Title\n"
        "Ada,Lovelace,ada@example.com,Countess\n"
        "Grace,Hopper,grace@example.com,Rear Admiral\n"
    )
    h, files = _upload(headers, csv_text)
    response = await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/contacts/import", headers=h, files=files
    )
    assert response.status_code == 201
    result = response.json()
    assert result["row_count"] == 2
    assert result["error_count"] == 0

    contacts = await client.get(f"/api/v1/tenants/current/companies/{company_id}/contacts", headers=headers)
    names = {(c["first_name"], c["last_name"], c["source"]) for c in contacts.json()}
    assert names == {("Ada", "Lovelace", "csv_import"), ("Grace", "Hopper", "csv_import")}


async def test_rows_missing_a_name_are_skipped_and_recorded(client: AsyncClient) -> None:
    headers, company_id = await _setup_company(client)
    csv_text = "first_name,last_name\nAda,Lovelace\n,NoFirstName\nNoLastName,\n"
    h, files = _upload(headers, csv_text)
    response = await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/contacts/import", headers=h, files=files
    )
    result = response.json()
    assert result["row_count"] == 1
    assert result["error_count"] == 2
    assert "Row 3" in result["errors"][0]


async def test_unrecognized_file_returns_422(client: AsyncClient) -> None:
    headers, company_id = await _setup_company(client)
    files = {"file": ("contacts.csv", io.BytesIO(b"\xff\xfe not valid utf8 \x00"), "text/csv")}
    response = await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/contacts/import", headers=headers, files=files
    )
    assert response.status_code == 422


async def test_viewer_cannot_import(client: AsyncClient) -> None:
    await signup(client, email="owner@example.com")
    tenant = (await create_tenant(client)).json()
    headers = tenant_headers(client, tenant["slug"])
    created = await client.post(
        "/api/v1/tenants/current/companies", json={"domain": "example.com"}, headers=headers
    )
    company_id = created.json()["id"]

    from tests.helpers import csrf_headers

    invite = await client.post(
        "/api/v1/tenants/current/invitations",
        json={"email": "viewer@example.com", "role": "viewer"},
        headers=headers,
    )
    token = invite.json()["token"]
    client.cookies.clear()
    await signup(client, email="viewer@example.com")
    await client.post(f"/api/v1/invitations/{token}/accept", headers=csrf_headers(client))

    h, files = _upload(tenant_headers(client, tenant["slug"]), "first_name,last_name\nAda,Lovelace\n")
    response = await client.post(
        f"/api/v1/tenants/current/companies/{company_id}/contacts/import", headers=h, files=files
    )
    assert response.status_code == 403
