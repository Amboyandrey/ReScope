"""Registering, listing, and removing a workspace's own provider credentials.

The plaintext key exists only for the moment it takes to validate and encrypt it — it's never
logged and never appears in any response after the credential is stored.
"""

import uuid
from collections.abc import Awaitable, Callable
from functools import partial

import anthropic
import httpx
import openai
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import EncryptedSecret, decrypt_secret, encrypt_secret
from app.core.errors import CredentialNotFound, CredentialValidationFailed
from app.llm import OPENAI_COMPATIBLE_BASE_URLS
from app.models import Provider, TenantCredential

_BROWSER_USE_ACCOUNT_URL = "https://api.browser-use.com/api/v2/billing/account"


async def _validate_anthropic_key(api_key: str) -> None:
    """A minimal, cheap call — this only needs to prove the key authenticates, not do real work."""
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
    except anthropic.APIStatusError as exc:
        raise CredentialValidationFailed(f"Anthropic rejected this key: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise CredentialValidationFailed("Could not reach Anthropic to validate this key.") from exc


async def _validate_browser_use_key(api_key: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(_BROWSER_USE_ACCOUNT_URL, headers={"X-Browser-Use-API-Key": api_key})
        except httpx.HTTPError as exc:
            raise CredentialValidationFailed("Could not reach Browser Use to validate this key.") from exc
    if response.status_code == 401:
        raise CredentialValidationFailed("Browser Use rejected this key.")
    if response.is_error:
        raise CredentialValidationFailed(
            f"Browser Use returned an unexpected error ({response.status_code})."
        )


async def _validate_openai_compatible_key(provider: Provider, api_key: str) -> None:
    """`GET /models` rather than a chat completion — the cheapest authenticated read every one of
    these providers exposes, and one that needs no model id guessed in advance (docs/PLAN.md
    §18). Confirming a *specific* model works is `validate_chat_model`'s job, done separately when
    a workspace picks one."""
    client = openai.AsyncOpenAI(api_key=api_key, base_url=OPENAI_COMPATIBLE_BASE_URLS[provider])
    try:
        await client.models.list()
    except openai.APIStatusError as exc:
        raise CredentialValidationFailed(
            f"{provider.value.title()} rejected this key: {exc.message}"
        ) from exc
    except openai.APIConnectionError as exc:
        raise CredentialValidationFailed(
            f"Could not reach {provider.value.title()} to validate this key."
        ) from exc


async def _validate_custom_endpoint(base_url: str, api_key: str) -> None:
    """A workspace's own OpenAI-compatible server rarely implements `GET /models` reliably
    (docs/PLAN.md §20) — this only proves `base_url` points at a real, reachable server. Any HTTP
    response counts, even a 401 or 404; only a connection failure fails this. The one-token
    `validate_chat_model` call at chat-model-save time is what actually proves the key and a
    specific model work together."""
    url = f"{base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        raise CredentialValidationFailed(f"Could not reach {base_url!r} to validate this key.") from exc


async def validate_chat_model(
    provider: Provider, api_key: str, model: str, *, base_url: str | None = None
) -> None:
    """Prove a specific model actually answers on this key — a one-token reply, the same "prove
    it works, do no real work" rule credential validation follows. Raised errors are the
    provider's own, surfaced verbatim so a typo'd model id fails with a message that says so.

    `base_url` is only meaningful for `Provider.CUSTOM`, whose endpoint the caller resolved from
    the workspace's own stored credential rather than a constant — ignored for every other
    provider, which already has one.
    """
    if provider == Provider.ANTHROPIC:
        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            await client.messages.create(
                model=model, max_tokens=1, messages=[{"role": "user", "content": "hi"}]
            )
        except anthropic.APIStatusError as exc:
            raise CredentialValidationFailed(f"Anthropic rejected model {model!r}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise CredentialValidationFailed("Could not reach Anthropic to validate this model.") from exc
        return

    resolved_base_url = base_url if provider == Provider.CUSTOM else OPENAI_COMPATIBLE_BASE_URLS[provider]
    openai_client = openai.AsyncOpenAI(api_key=api_key, base_url=resolved_base_url)
    try:
        await openai_client.chat.completions.create(
            model=model, max_tokens=1, messages=[{"role": "user", "content": "hi"}]
        )
    except openai.APIStatusError as exc:
        raise CredentialValidationFailed(
            f"{provider.value.title()} rejected model {model!r}: {exc.message}"
        ) from exc
    except openai.APIConnectionError as exc:
        raise CredentialValidationFailed(
            f"Could not reach {provider.value.title()} to validate this model."
        ) from exc


_VALIDATORS: dict[Provider, Callable[[str], Awaitable[None]]] = {
    Provider.ANTHROPIC: _validate_anthropic_key,
    Provider.BROWSER_USE: _validate_browser_use_key,
    Provider.OPENAI: partial(_validate_openai_compatible_key, Provider.OPENAI),
    Provider.GEMINI: partial(_validate_openai_compatible_key, Provider.GEMINI),
    Provider.NEBIUS: partial(_validate_openai_compatible_key, Provider.NEBIUS),
}


async def set_credential(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    created_by: uuid.UUID,
    provider: Provider,
    api_key: str,
    base_url: str | None = None,
) -> TenantCredential:
    """Validate a key against its own provider, then store it encrypted — replacing any existing
    key for this provider (`UNIQUE(tenant_id, provider)`), never storing one unvalidated.

    `base_url` is only stored for `Provider.CUSTOM` — every other provider's endpoint is a
    constant, so a value passed for one is silently dropped rather than trusted."""
    if provider == Provider.CUSTOM:
        if not base_url:
            raise CredentialValidationFailed("The custom provider requires a base_url.")
        await _validate_custom_endpoint(base_url, api_key)
    else:
        base_url = None
        await _VALIDATORS[provider](api_key)

    secret = encrypt_secret(api_key)
    stmt = (
        pg_insert(TenantCredential)
        .values(
            tenant_id=tenant_id,
            provider=provider,
            ciphertext=secret.ciphertext,
            nonce=secret.nonce,
            wrapped_key=secret.wrapped_key,
            base_url=base_url,
            last4=api_key[-4:],
            created_by=created_by,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "provider"],
            set_={
                "ciphertext": secret.ciphertext,
                "nonce": secret.nonce,
                "wrapped_key": secret.wrapped_key,
                "base_url": base_url,
                "last4": api_key[-4:],
                "created_by": created_by,
                "validated_at": pg_insert(TenantCredential).excluded.validated_at,
            },
        )
        .returning(TenantCredential)
    )
    credential = (await db.scalars(stmt)).one()
    await db.flush()
    # A conflict update reuses the existing row's id — if this session already holds that id in
    # its identity map (only possible within one session across two calls, as in a test; a fresh
    # per-request session never does), the ORM returns the cached, now-stale object rather than
    # rematerializing it from this statement's own RETURNING data. refresh() forces a real read.
    await db.refresh(credential)
    return credential


async def list_credentials(db: AsyncSession, *, tenant_id: uuid.UUID) -> list[TenantCredential]:
    stmt = (
        select(TenantCredential)
        .where(TenantCredential.tenant_id == tenant_id)
        .order_by(TenantCredential.provider)
    )
    return list((await db.scalars(stmt)).all())


async def get_active_credential(
    db: AsyncSession, *, tenant_id: uuid.UUID, provider: Provider
) -> TenantCredential | None:
    """The tenant's own credential for `provider`, or `None` if it has none — the resolution
    layer (app/services/llm.py) falls back to the platform's own key in that case."""
    credential: TenantCredential | None = await db.scalar(
        select(TenantCredential).where(
            TenantCredential.tenant_id == tenant_id, TenantCredential.provider == provider
        )
    )
    return credential


async def remove_credential(db: AsyncSession, *, tenant_id: uuid.UUID, provider: Provider) -> None:
    credential = await get_active_credential(db, tenant_id=tenant_id, provider=provider)
    if credential is None:
        raise CredentialNotFound()
    await db.delete(credential)
    await db.flush()


def decrypt_credential_key(credential: TenantCredential) -> str:
    """Decrypt a credential's API key — for the resolution layer's use only, never a router."""
    secret = EncryptedSecret(
        ciphertext=credential.ciphertext, nonce=credential.nonce, wrapped_key=credential.wrapped_key
    )
    return decrypt_secret(secret)
