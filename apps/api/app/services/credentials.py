"""Registering, listing, and removing a workspace's own provider credentials.

The plaintext key exists only for the moment it takes to validate and encrypt it — it's never
logged and never appears in any response after the credential is stored.
"""

import uuid

import anthropic
import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import EncryptedSecret, decrypt_secret, encrypt_secret
from app.core.errors import CredentialNotFound, CredentialValidationFailed
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


_VALIDATORS = {Provider.ANTHROPIC: _validate_anthropic_key, Provider.BROWSER_USE: _validate_browser_use_key}


async def set_credential(
    db: AsyncSession, *, tenant_id: uuid.UUID, created_by: uuid.UUID, provider: Provider, api_key: str
) -> TenantCredential:
    """Validate a key against its own provider, then store it encrypted — replacing any existing
    key for this provider (`UNIQUE(tenant_id, provider)`), never storing one unvalidated."""
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
            last4=api_key[-4:],
            created_by=created_by,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "provider"],
            set_={
                "ciphertext": secret.ciphertext,
                "nonce": secret.nonce,
                "wrapped_key": secret.wrapped_key,
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
