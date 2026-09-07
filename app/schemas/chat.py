from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.models import AgentRole


class MessageDTO(BaseModel):
    role: str
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    thread_id: str | None = Field(default=None, description="Si se omite, se genera uno nuevo")
    user_id: str | None = Field(default=None, max_length=128)
    metadata: dict[str, str] = Field(default_factory=dict)


class RetrievalSource(BaseModel):
    document_id: str
    filename: str
    page: int | None = None
    score: float | None = None


class ChatResponse(BaseModel):
    thread_id: str
    message: str
    agent: AgentRole
    escalated: bool = False
    escalation_ticket_id: UUID | None = None
    sources: list[RetrievalSource] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StreamChunk(BaseModel):
    thread_id: str
    delta: str
    agent: AgentRole | None = None
    done: bool = False
