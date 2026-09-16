"""Creating a tenant, listing the ones a user belongs to, and resolving one by slug."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import set_tenant_scope
from app.core.errors import (
    BrowserUseKeyRequired,
    ChatKeyRequired,
    CredentialValidationFailed,
    SlugReserved,
    SlugTaken,
    TenantNotFound,
)
from app.core.slugify import RESERVED_SLUGS, slugify
from app.llm import CHAT_PROVIDERS
from app.models import Membership, Provider, Role, ScrapeProvider, Tenant, User
from app.services.credentials import decrypt_credential_key, get_active_credential, validate_chat_model
from app.services.llm import resolve_anthropic_key, resolve_browser_use_key

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


async def create_tenant(db: AsyncSession, *, owner: User, name: str, slug: str | None = None) -> Tenant:
    """Create a tenant and make `owner` its first (and, at this point, only) owner.

    The tenant's id is generated in application code — not left to the mapper's own `default=
    uuid.uuid4`, which only fires when the row is flushed — specifically so its RLS scope can be
    set *before* the row is written. The `INSERT ... RETURNING` Postgres runs under the hood is
    itself subject to the SELECT policy, and this is what lets it pass on the very first write.
    """
    slug = slugify(slug or name)
    if slug in RESERVED_SLUGS:
        raise SlugReserved()
    if not _SLUG_RE.match(slug):
        raise SlugReserved()

    tenant_id = uuid.uuid4()
    await set_tenant_scope(db, tenant_id)
    tenant = Tenant(id=tenant_id, name=name.strip(), slug=slug)
    db.add(tenant)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise SlugTaken() from exc

    db.add(Membership(tenant_id=tenant.id, user_id=owner.id, role=Role.OWNER))
    await db.flush()
    return tenant


async def list_my_tenants(db: AsyncSession, *, user: User) -> list[tuple[Tenant, Role]]:
    """List every tenant a user belongs to, with their role in each — no single tenant is in
    scope for this query, so it relies on `memberships`' RLS predicate matching by user id alone."""
    stmt = (
        select(Tenant, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == user.id)
        .order_by(Tenant.name)
    )
    return [(t, r) for t, r in (await db.execute(stmt)).all()]


async def get_tenant_and_role_by_slug(db: AsyncSession, *, slug: str, user: User) -> tuple[Tenant, Role]:
    """Resolve a tenant by its subdomain slug and the caller's role in it, or 404.

    Runs *before* `set_tenant_scope` — the tenant isn't confirmed to be in scope yet, so this
    relies on `tenants`' RLS predicate matching by the caller's own memberships, same as
    `list_my_tenants`. Once this returns, the caller sets the tenant scope for everything after.
    """
    stmt = (
        select(Tenant, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Tenant.slug == slug, Membership.user_id == user.id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise TenantNotFound()
    tenant, role = row
    return tenant, role


async def set_scrape_provider(db: AsyncSession, *, tenant: Tenant, provider: ScrapeProvider) -> Tenant:
    """Switch which Tier 2 provider this tenant's deep-mode jobs use (docs/PLAN.md §13). Refuses
    to switch to Browser Use Cloud without a usable key — a tenant's own, or the platform's —
    since otherwise a deep-mode job would just silently run as if it were fast mode instead."""
    if provider == ScrapeProvider.BROWSER_USE_CLOUD:
        resolved = await resolve_browser_use_key(db, tenant_id=tenant.id)
        if resolved is None:
            raise BrowserUseKeyRequired()
    tenant.settings = {**tenant.settings, "scrape_provider": provider.value}
    await db.flush()
    return tenant


async def set_chat_model(db: AsyncSession, *, tenant: Tenant, provider: Provider, model: str) -> Tenant:
    """Switch which provider and model answer this tenant's chat messages (docs/PLAN.md §18).

    Refuses a provider the tenant has no usable key for — Anthropic falls back to the platform's
    own key like every other Anthropic call, but the other providers have no platform key, so a
    tenant must register its own before picking one. Refuses a model that doesn't actually answer
    on that key too, so a typo'd model id fails here rather than on the next chat message.
    """
    if provider not in CHAT_PROVIDERS:
        raise CredentialValidationFailed(f"{provider.value.title()} isn't a chat provider.")

    base_url = None
    if provider == Provider.ANTHROPIC:
        api_key = (await resolve_anthropic_key(db, tenant_id=tenant.id)).api_key
    else:
        credential = await get_active_credential(db, tenant_id=tenant.id, provider=provider)
        if credential is None:
            raise ChatKeyRequired()
        api_key = decrypt_credential_key(credential)
        base_url = credential.base_url

    await validate_chat_model(provider, api_key, model, base_url=base_url)
    tenant.settings = {**tenant.settings, "chat": {"provider": provider.value, "model": model}}
    await db.flush()
    return tenant
