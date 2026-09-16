"""A member's own chat over the tenant's catalogue (docs/PLAN.md §14) — personal, like a saved
search, not shared with the rest of the tenant."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Conversation(Base, UUIDPrimaryKeyMixin):
    """One chat thread. `UNIQUE(tenant_id, id)` so `messages` can declare a composite foreign key
    back to it, the same pattern every other tenant-scoped parent table in this app uses."""

    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base, UUIDPrimaryKeyMixin):
    """One turn in a conversation. `citations` is a list of `{company_id, source_kind}` resolved
    from the retrieved context the model actually saw — never a name the model merely wrote."""

    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID] = mapped_column()
    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role"))
    content: Mapped[str] = mapped_column()
    citations: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list, server_default="[]")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
