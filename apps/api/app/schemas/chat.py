"""Request/response shapes for conversations and their messages."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.company import CompanyType, CompetencyKind
from app.models.conversation import MessageRole


class CreateConversationRequest(BaseModel):
    title: str = Field(default="New chat", max_length=200)


class ConversationResponse(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    # The same catalogue filters the /catalogue page uses (docs/PLAN.md §14) — narrows retrieval
    # before ranking rather than leaving it to the model to notice a scope the question implied.
    country: str | None = Field(default=None, max_length=2)
    company_type: CompanyType | None = None
    industry: str | None = Field(default=None, max_length=120)
    competency_kind: CompetencyKind | None = None
    tag: uuid.UUID | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[dict[str, str]]
    created_at: datetime

    model_config = {"from_attributes": True}
