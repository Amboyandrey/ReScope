"""Resolving which Anthropic key a tenant's model calls run on — its own registered key when it
has one, the platform's otherwise (docs/PLAN.md §12) — and what that resolution means for quotas
and billing.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Provider, UsageBilledTo
from app.services.credentials import decrypt_credential_key, get_active_credential


@dataclass(frozen=True)
class ResolvedKey:
    api_key: str
    billed_to: UsageBilledTo


async def resolve_anthropic_key(db: AsyncSession, *, tenant_id: uuid.UUID) -> ResolvedKey:
    """The tenant's own Anthropic key if it has registered one, else the platform's."""
    credential = await get_active_credential(db, tenant_id=tenant_id, provider=Provider.ANTHROPIC)
    if credential is not None:
        return ResolvedKey(api_key=decrypt_credential_key(credential), billed_to=UsageBilledTo.TENANT)
    return ResolvedKey(api_key=get_settings().anthropic_api_key, billed_to=UsageBilledTo.PLATFORM)


async def has_own_anthropic_key(db: AsyncSession, *, tenant_id: uuid.UUID) -> bool:
    """Whether quota checks should be skipped for this tenant — usage is still metered either
    way (see services/usage.py's `billed_to`), just not counted against the plan's ceiling."""
    credential = await get_active_credential(db, tenant_id=tenant_id, provider=Provider.ANTHROPIC)
    return credential is not None
