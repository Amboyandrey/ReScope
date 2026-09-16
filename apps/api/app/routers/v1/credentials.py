"""A workspace's own Anthropic and Browser Use keys — admin/owner only, since a compromised key
here spends the workspace's own money and reaches its own provider account."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import Provider, Role
from app.schemas.credential import CredentialResponse, SetCredentialRequest
from app.services.audit import record_audit
from app.services.credentials import list_credentials, remove_credential, set_credential

router = APIRouter(prefix="/tenants/current/credentials", tags=["credentials"])

_AdminCtx = Annotated[TenantCtx, Depends(require_role(Role.ADMIN))]


@router.get("", response_model=list[CredentialResponse])
async def list_all(ctx: _AdminCtx, db: DbSession) -> list[CredentialResponse]:
    credentials = await list_credentials(db, tenant_id=ctx.tenant.id)
    return [CredentialResponse.model_validate(c) for c in credentials]


@router.put("", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def set_one(body: SetCredentialRequest, ctx: _AdminCtx, db: DbSession) -> CredentialResponse:
    """Validate the key against its own provider, then store it — replacing any existing key for
    this provider."""
    credential = await set_credential(
        db,
        tenant_id=ctx.tenant.id,
        created_by=ctx.user.id,
        provider=body.provider,
        api_key=body.api_key,
    )
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="credential.set",
        target_type="tenant_credential",
        target_id=str(credential.id),
        metadata={"provider": body.provider.value, "last4": credential.last4},
    )
    return CredentialResponse.model_validate(credential)


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_one(provider: Provider, ctx: _AdminCtx, db: DbSession) -> None:
    await remove_credential(db, tenant_id=ctx.tenant.id, provider=provider)
    await record_audit(
        db,
        tenant_id=ctx.tenant.id,
        actor_id=ctx.user.id,
        action="credential.removed",
        target_type="tenant_credential",
        target_id=provider.value,
    )
