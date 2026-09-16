"""Resolving which Anthropic key a tenant's model calls run on — its own registered key when it
has one, the platform's otherwise (docs/PLAN.md §12) — and what that resolution means for quotas
and billing.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ChatKeyRequired, CredentialNotFound, CredentialValidationFailed
from app.llm import CHAT_PROVIDERS
from app.models import Provider, Tenant, UsageBilledTo
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


@dataclass(frozen=True)
class ResolvedChatModel:
    provider: Provider
    model: str
    api_key: str
    billed_to: UsageBilledTo
    # Only set for `Provider.CUSTOM` (docs/PLAN.md §22) — every other provider has a constant
    # endpoint `build_chat_provider` already knows.
    base_url: str | None = None


async def resolve_chat_model(db: AsyncSession, *, tenant: Tenant) -> ResolvedChatModel:
    """The provider, model, and key this tenant's chat messages currently run on (docs/PLAN.md
    §18). Anthropic falls back to the platform's own key like every other Anthropic call; the
    other providers have no platform key, so a tenant configured for one of them must have
    registered its own (`set_chat_model` refuses to save that choice otherwise)."""
    provider, model = tenant.chat_provider, tenant.chat_model
    if provider == Provider.ANTHROPIC:
        resolved = await resolve_anthropic_key(db, tenant_id=tenant.id)
        return ResolvedChatModel(
            provider=provider, model=model, api_key=resolved.api_key, billed_to=resolved.billed_to
        )

    credential = await get_active_credential(db, tenant_id=tenant.id, provider=provider)
    if credential is None:
        raise CredentialNotFound()
    return ResolvedChatModel(
        provider=provider,
        model=model,
        api_key=decrypt_credential_key(credential),
        billed_to=UsageBilledTo.TENANT,
        base_url=credential.base_url,
    )


async def resolve_key_for_chat_provider(
    db: AsyncSession, *, tenant: Tenant, provider: Provider
) -> tuple[str, str | None]:
    """The `(api_key, base_url)` a workspace would use to talk to `provider` for chat — its own
    key for every provider but Anthropic, which falls back to the platform's; `base_url` is only
    ever non-`None` for `Provider.CUSTOM`. Raises `ChatKeyRequired` when the workspace has no
    usable key for `provider`. Shared by `set_chat_model` (saving a chat choice) and the
    available-models endpoint (browsing a provider's models before committing to one)."""
    if provider not in CHAT_PROVIDERS:
        raise CredentialValidationFailed(f"{provider.value.title()} isn't a chat provider.")
    if provider == Provider.ANTHROPIC:
        return (await resolve_anthropic_key(db, tenant_id=tenant.id)).api_key, None
    credential = await get_active_credential(db, tenant_id=tenant.id, provider=provider)
    if credential is None:
        raise ChatKeyRequired()
    return decrypt_credential_key(credential), credential.base_url


async def has_own_chat_key(db: AsyncSession, *, tenant: Tenant) -> bool:
    """Whether this tenant is exempt from the chat quota — on its own key, for whichever provider
    its chat is currently configured to use (docs/PLAN.md §18 generalizes the Anthropic-only
    exemption from §12 to all four chat providers)."""
    credential = await get_active_credential(db, tenant_id=tenant.id, provider=tenant.chat_provider)
    return credential is not None


async def resolve_browser_use_key(db: AsyncSession, *, tenant_id: uuid.UUID) -> ResolvedKey | None:
    """The tenant's own Browser Use key if it has registered one, else the platform's — `None` if
    neither exists, which is what greys out the `browser_use_cloud` provider option in settings
    and is what `run_browser_use_task` treats as "this provider isn't usable right now"."""
    credential = await get_active_credential(db, tenant_id=tenant_id, provider=Provider.BROWSER_USE)
    if credential is not None:
        return ResolvedKey(api_key=decrypt_credential_key(credential), billed_to=UsageBilledTo.TENANT)
    platform_key = get_settings().browser_use_api_key
    if not platform_key:
        return None
    return ResolvedKey(api_key=platform_key, billed_to=UsageBilledTo.PLATFORM)


async def has_own_browser_use_key(db: AsyncSession, *, tenant_id: uuid.UUID) -> bool:
    credential = await get_active_credential(db, tenant_id=tenant_id, provider=Provider.BROWSER_USE)
    return credential is not None
