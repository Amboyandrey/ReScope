"""CSV import — contacts only for now (see app/models/import_job.py's `ImportKind`).

Processed synchronously: a contacts CSV is small enough that this never needed its own background
job the way scraping does. Column names are matched case-insensitively against a small set of
aliases rather than requiring an exact header — nobody's CRM export uses the same column names.
"""

import csv
import io
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Contact, Import, ImportKind, ImportStatus

MAX_ROWS = 5000

# Each entry: the field it fills, and every header alias (already lowercased/stripped) that means it.
_COLUMN_ALIASES: dict[str, list[str]] = {
    "first_name": ["first_name", "firstname", "first"],
    "last_name": ["last_name", "lastname", "last", "surname"],
    "email": ["email", "email_address"],
    "title": ["title", "job_title", "role", "position"],
    "phone": ["phone", "phone_number", "mobile"],
    "linkedin_url": ["linkedin_url", "linkedin", "linkedin_profile"],
}


class ImportTooLarge(AppError):
    status_code = 413
    detail = f"CSV files are limited to {MAX_ROWS} rows."


class InvalidCsv(AppError):
    status_code = 422
    detail = "Could not read this file as CSV — check it's UTF-8 encoded with a header row."


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace(" ", "_").replace("-", "_")


def _build_column_map(headers: list[str]) -> dict[str, str]:
    """`{csv_header: field_name}` for every recognized column — unrecognized columns are ignored."""
    normalized = {h: _normalize_header(h) for h in headers}
    column_map: dict[str, str] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for header, norm in normalized.items():
            if norm in aliases:
                column_map[header] = field
                break
    return column_map


async def import_contacts_csv(
    db: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, created_by: uuid.UUID, csv_bytes: bytes
) -> Import:
    """Parse `csv_bytes` and create one contact per valid row. Never raises for a bad *row* — only
    for a file that can't be read as CSV at all; a row missing a required field is skipped and
    recorded in `errors`, and the import still completes with whatever rows were good.
    """
    try:
        text = csv_bytes.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise InvalidCsv()
        column_map = _build_column_map(list(reader.fieldnames))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise InvalidCsv() from exc

    if len(rows) > MAX_ROWS:
        raise ImportTooLarge()

    errors: list[str] = []
    created = 0
    for i, row in enumerate(rows, start=2):  # row 1 is the header
        fields = {field: (row.get(header) or "").strip() for header, field in column_map.items()}
        first_name = fields.get("first_name", "")
        last_name = fields.get("last_name", "")
        if not first_name or not last_name:
            errors.append(f"Row {i}: missing first or last name — skipped.")
            continue
        db.add(
            Contact(
                tenant_id=tenant_id,
                company_id=company_id,
                first_name=first_name,
                last_name=last_name,
                email=fields.get("email") or None,
                title=fields.get("title") or None,
                phone=fields.get("phone") or None,
                linkedin_url=fields.get("linkedin_url") or None,
                source="csv_import",
            )
        )
        created += 1

    record = Import(
        tenant_id=tenant_id,
        kind=ImportKind.CONTACTS,
        status=ImportStatus.DONE,
        row_count=created,
        error_count=len(errors),
        errors=errors[:100],  # capped — a malformed file with thousands of bad rows shouldn't bloat this row
        created_by=created_by,
    )
    db.add(record)
    await db.flush()
    return record
