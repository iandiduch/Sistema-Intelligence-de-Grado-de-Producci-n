from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import (
    ContactChannel,
    EscalationPriority,
    EscalationStatus,
    EscalationType,
)
from app.schemas.chat import MessageDTO


class EscalationTicketCreate(BaseModel):
    thread_id: str
    original_question: str = Field(..., min_length=1)
    relevant_history: list[MessageDTO] = Field(default_factory=list)
    reason: str = Field(..., min_length=1, max_length=2000)
    escalation_type: EscalationType
    priority: EscalationPriority = EscalationPriority.MEDIUM
    contact_channel: ContactChannel
    contact_value: str = Field(..., min_length=3, max_length=200)


class EscalationTicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: UUID
    thread_id: str
    status: EscalationStatus
    priority: EscalationPriority
    reason: str
    escalation_type: EscalationType
    original_question: str
    relevant_history: list[MessageDTO] = Field(default_factory=list)
    contact_channel: ContactChannel
    contact_value: str
    resolution_notes: str | None = None
    resolved_by: str | None = None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None = None


class EscalationResolveRequest(BaseModel):
    resolution_notes: str = Field(..., min_length=1, max_length=4000)
    resolved_by: str | None = Field(default=None, max_length=128)
