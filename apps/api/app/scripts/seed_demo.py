"""Seeds a fixed "demo" tenant with a couple of fully-profiled (fictional) companies and some
light-CRM data, so a fresh deploy has something to show without needing a real Anthropic API key
or waiting on an actual scrape to finish. Safe to re-run — exits without changes if the tenant
already exists.

Usage: uv run python -m app.scripts.seed_demo [email] [password]
"""

import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.db import async_session_factory, set_tenant_scope
from app.core.security import hash_password
from app.models import (
    Company,
    CompanyTag,
    Competency,
    CompetencyKind,
    Contact,
    Note,
    Offering,
    OfferingKind,
    ProfileStatus,
    Tag,
    Tenant,
    User,
)
from app.services.tenants import create_tenant

DEMO_SLUG = "demo"
DEMO_TENANT_NAME = "Demo Workspace"
DEFAULT_EMAIL = "demo@rescope.app"
DEFAULT_PASSWORD = "demo-password-123"

_COMPANIES = [
    {
        "domain": "nimbusrobotics.example",
        "name": "Nimbus Robotics",
        "overview": (
            "Nimbus Robotics builds warehouse picking arms and the vision software that guides "
            "them, selling directly to mid-size logistics operators who can't justify a "
            "custom-integration project."
        ),
        "offerings": [
            (OfferingKind.PRODUCT, "PickArm-3", "A six-axis picking arm rated for 8-hour shifts."),
            (
                OfferingKind.SERVICE,
                "Fleet monitoring",
                "Uptime and throughput dashboards for a warehouse's arms.",
            ),
        ],
        "competencies": [
            (
                CompetencyKind.TECHNOLOGY,
                "Computer vision",
                "In-house model for bin-picking in cluttered totes.",
            ),
            (
                CompetencyKind.CERTIFICATION,
                "ISO 10218",
                "Certified to the industrial robot safety standard.",
            ),
        ],
        "tag": ("Robotics", "#2563eb"),
        "contact": ("Priya", "Nair", "priya@nimbusrobotics.example", "VP Operations"),
    },
    {
        "domain": "solsticeanalytics.example",
        "name": "Solstice Analytics",
        "overview": (
            "Solstice Analytics is a usage-based billing platform for B2B SaaS companies, "
            "positioned against building metering in-house."
        ),
        "offerings": [
            (OfferingKind.PRODUCT, "Meter", "Event ingestion and usage aggregation SDK."),
            (
                OfferingKind.PRODUCT,
                "Invoice Engine",
                "Turns aggregated usage into invoices on any billing cycle.",
            ),
        ],
        "competencies": [
            (
                CompetencyKind.CAPABILITY,
                "Real-time aggregation",
                "Sub-second usage counters at high write volume.",
            ),
            (CompetencyKind.PARTNERSHIP, "Stripe", "Native connector for Stripe-based billing."),
        ],
        "tag": ("SaaS", "#059669"),
        "contact": ("Marcus", "Webb", "marcus@solsticeanalytics.example", "Head of Partnerships"),
    },
]


async def seed(email: str, password: str) -> None:
    async with async_session_factory() as db:
        existing = await db.scalar(select(Tenant).where(Tenant.slug == DEMO_SLUG))
        if existing is not None:
            print(f"Demo tenant already exists at slug '{DEMO_SLUG}' — nothing to do.")
            return

        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash=hash_password(password), display_name="Demo")
            db.add(user)
            await db.flush()

        tenant = await create_tenant(db, owner=user, name=DEMO_TENANT_NAME, slug=DEMO_SLUG)
        await set_tenant_scope(db, tenant.id)  # stays set for the rest of this transaction

        for spec in _COMPANIES:
            company = Company(
                tenant_id=tenant.id,
                domain=spec["domain"],
                name=spec["name"],
                website_url=f"https://{spec['domain']}",
                overview=spec["overview"],
                profile_status=ProfileStatus.DONE,
                last_profiled_at=datetime.now(UTC),
                created_by=user.id,
            )
            db.add(company)
            await db.flush()

            for kind, name, description in spec["offerings"]:
                db.add(
                    Offering(
                        tenant_id=tenant.id,
                        company_id=company.id,
                        kind=kind,
                        name=name,
                        description=description,
                        evidence=[{"url": company.website_url, "quote": description}],
                    )
                )
            for kind, name, description in spec["competencies"]:
                db.add(
                    Competency(
                        tenant_id=tenant.id,
                        company_id=company.id,
                        kind=kind,
                        name=name,
                        description=description,
                        evidence=[{"url": company.website_url, "quote": description}],
                    )
                )

            tag_name, tag_color = spec["tag"]
            tag = Tag(tenant_id=tenant.id, name=tag_name, color=tag_color)
            db.add(tag)
            await db.flush()
            db.add(CompanyTag(tenant_id=tenant.id, company_id=company.id, tag_id=tag.id))

            first_name, last_name, contact_email, title = spec["contact"]
            db.add(
                Contact(
                    tenant_id=tenant.id,
                    company_id=company.id,
                    first_name=first_name,
                    last_name=last_name,
                    email=contact_email,
                    title=title,
                )
            )
            db.add(
                Note(
                    tenant_id=tenant.id,
                    company_id=company.id,
                    author_id=user.id,
                    body=f"Sourced from {spec['domain']} — a good fit to reach out to this quarter.",
                )
            )

        await db.commit()
        print(f"Seeded '{DEMO_SLUG}' — sign in as {email} / {password}")


if __name__ == "__main__":
    seed_email = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL
    seed_password = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PASSWORD
    asyncio.run(seed(seed_email, seed_password))
