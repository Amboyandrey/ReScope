"""Conversations, their messages, and streaming a new reply — retrieval-grounded chat over a
tenant's catalogue (docs/PLAN.md §14)."""

import json
import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Annotated, cast

import anthropic
from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.core.db import async_session_factory, set_tenant_scope
from app.deps.db import DbSession
from app.deps.tenant import TenantCtx, require_role
from app.models import MessageRole, Role, UsageKind
from app.schemas.chat import (
    ConversationResponse,
    CreateConversationRequest,
    MessageResponse,
    SendMessageRequest,
)
from app.services.catalogue import CatalogueFilters
from app.services.chat import (
    SYSTEM_PROMPT,
    add_message,
    build_context,
    create_conversation,
    delete_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    recent_history_for_prompt,
    resolve_citations,
    retrieve_context,
)
from app.services.llm import resolve_anthropic_key
from app.services.quotas import assert_within_chat_quota
from app.services.usage import record_usage_event

router = APIRouter(prefix="/tenants/current/conversations", tags=["chat"])

_ViewerCtx = Annotated[TenantCtx, Depends(require_role(Role.VIEWER))]

CHAT_MODEL = "claude-sonnet-5"
CHAT_MAX_TOKENS = 2048
# Anthropic doesn't publish a chat-specific rate card here the way docs/PLAN.md §5 has one for
# extraction — reuses that same Sonnet rate, the closest real number available.
_CHAT_INPUT_COST_PER_MTOK = Decimal("2.00")
_CHAT_OUTPUT_COST_PER_MTOK = Decimal("10.00")


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create(body: CreateConversationRequest, ctx: _ViewerCtx, db: DbSession) -> ConversationResponse:
    conversation = await create_conversation(
        db, tenant_id=ctx.tenant.id, owner_id=ctx.user.id, title=body.title
    )
    return ConversationResponse.model_validate(conversation)


@router.get("", response_model=list[ConversationResponse])
async def list_all(ctx: _ViewerCtx, db: DbSession) -> list[ConversationResponse]:
    conversations = await list_conversations(db, tenant_id=ctx.tenant.id, owner_id=ctx.user.id)
    return [ConversationResponse.model_validate(c) for c in conversations]


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(conversation_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession) -> None:
    await delete_conversation(
        db, tenant_id=ctx.tenant.id, owner_id=ctx.user.id, conversation_id=conversation_id
    )


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_conversation_messages(
    conversation_id: uuid.UUID, ctx: _ViewerCtx, db: DbSession
) -> list[MessageResponse]:
    await get_conversation(db, tenant_id=ctx.tenant.id, owner_id=ctx.user.id, conversation_id=conversation_id)
    messages = await list_messages(db, tenant_id=ctx.tenant.id, conversation_id=conversation_id)
    return [MessageResponse.model_validate(m) for m in messages]


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: uuid.UUID, body: SendMessageRequest, ctx: _ViewerCtx, db: DbSession
) -> StreamingResponse:
    """Persist the user's turn, then stream the assistant's reply back as Server-Sent Events: a
    `data:` line per token of text, then `event: citations` and `event: done` once the reply is
    complete and persisted. No resume — a dropped connection loses the in-flight reply and the
    client re-asks, the deliberately simple trade-off this makes over ReCore's own resumable
    streaming (docs/PLAN.md §14).

    Everything after the response object is returned runs on its own database session, not the
    request-scoped one: FastAPI tears down `db`'s dependency (committing it) the moment this
    function returns the `StreamingResponse`, before the streaming body below has actually run.
    """
    conversation = await get_conversation(
        db, tenant_id=ctx.tenant.id, owner_id=ctx.user.id, conversation_id=conversation_id
    )
    await assert_within_chat_quota(db, tenant=ctx.tenant)

    filters = CatalogueFilters(
        country=body.country.upper() if body.country else None,
        company_type=body.company_type,
        industry=body.industry,
        competency_kind=body.competency_kind,
        tag_id=body.tag,
    )
    items = await retrieve_context(db, tenant_id=ctx.tenant.id, query=body.content, filters=filters)
    context = build_context(items)
    history = await recent_history_for_prompt(db, tenant_id=ctx.tenant.id, conversation_id=conversation.id)
    resolved_key = await resolve_anthropic_key(db, tenant_id=ctx.tenant.id)

    await add_message(
        db,
        tenant_id=ctx.tenant.id,
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content=body.content,
    )
    await db.commit()

    tenant_id = ctx.tenant.id

    async def stream() -> AsyncIterator[str]:
        client = anthropic.AsyncAnthropic(api_key=resolved_key.api_key)
        system_prompt = f"{SYSTEM_PROMPT}\n\nContext:\n{context}" if context else SYSTEM_PROMPT
        anthropic_messages = [*history, {"role": "user", "content": body.content}]
        answer = ""
        tokens_in = tokens_out = 0
        try:
            async with client.messages.stream(
                model=CHAT_MODEL,
                max_tokens=CHAT_MAX_TOKENS,
                system=system_prompt,
                messages=cast("list[anthropic.types.MessageParam]", anthropic_messages),
            ) as message_stream:
                async for text in message_stream.text_stream:
                    answer += text
                    yield f"data: {json.dumps(text)}\n\n"
                final = await message_stream.get_final_message()
                tokens_in, tokens_out = final.usage.input_tokens, final.usage.output_tokens
        except Exception as exc:  # noqa: BLE001 — surfaced as an error event, not a broken stream
            yield f"event: error\ndata: {json.dumps(str(exc))}\n\n"
            return

        citations = resolve_citations(answer, items)
        cost = (
            Decimal(tokens_in) / 1_000_000 * _CHAT_INPUT_COST_PER_MTOK
            + Decimal(tokens_out) / 1_000_000 * _CHAT_OUTPUT_COST_PER_MTOK
        )

        async with async_session_factory() as stream_db:
            await set_tenant_scope(stream_db, tenant_id)
            await add_message(
                stream_db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                citations=citations,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            await record_usage_event(
                stream_db,
                tenant_id=tenant_id,
                job_id=None,
                kind=UsageKind.CHAT,
                model=CHAT_MODEL,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=float(cost),
                billed_to=resolved_key.billed_to,
            )
            await stream_db.commit()

        yield f"event: citations\ndata: {json.dumps(citations)}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
