"""CRUD de tickets HOTL sobre escalation_tickets. Los agentes nunca tocan
SQLAlchemy directo: siempre pasan por este servicio."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateTransitionError, TicketNotFoundError
from app.core.metrics import HOTL_TICKETS_TOTAL
from app.db.models_orm import EscalationTicket
from app.domain.models import (
    ContactChannel,
    EscalationPriority,
    EscalationStatus,
    EscalationType,
)
from app.schemas.chat import MessageDTO
from app.schemas.escalation import EscalationTicketResponse
from app.services.notification_service import HOTLNotificationService


class EscalationService:
    def __init__(
        self,
        session: AsyncSession,
        notification_service: HOTLNotificationService | None = None,
    ) -> None:
        self._session = session
        self._notification_service = notification_service

    async def create_ticket(
        self,
        *,
        thread_id: str,
        original_question: str,
        relevant_history: list[MessageDTO],
        reason: str,
        escalation_type: EscalationType,
        contact_channel: ContactChannel,
        contact_value: str,
        priority: EscalationPriority = EscalationPriority.MEDIUM,
    ) -> EscalationTicketResponse:
        ticket = EscalationTicket(
            thread_id=thread_id,
            original_question=original_question,
            relevant_history=[m.model_dump(mode="json") for m in relevant_history],
            reason=reason,
            escalation_type=escalation_type.value,
            priority=priority.value,
            contact_channel=contact_channel.value,
            contact_value=contact_value,
            status=EscalationStatus.PENDING.value,
        )
        self._session.add(ticket)
        await self._session.flush()
        await self._session.refresh(ticket)
        response = EscalationTicketResponse.model_validate(ticket, from_attributes=True)

        HOTL_TICKETS_TOTAL.labels(
            priority=priority.value,
            channel=contact_channel.value,
            escalation_type=escalation_type.value,
        ).inc()

        if self._notification_service is not None:
            await self._notification_service.notify_ticket_created(response)

        return response

    async def get_ticket(self, ticket_id: UUID) -> EscalationTicketResponse:
        ticket = await self._session.get(EscalationTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(f"Ticket {ticket_id} no encontrado")
        return EscalationTicketResponse.model_validate(ticket, from_attributes=True)

    async def list_tickets(
        self,
        *,
        status: EscalationStatus | None = None,
        channel: ContactChannel | None = None,
        priority: EscalationPriority | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EscalationTicketResponse]:
        stmt = select(EscalationTicket).order_by(EscalationTicket.created_at.desc()).limit(limit).offset(offset)
        if status is not None:
            stmt = stmt.where(EscalationTicket.status == status.value)
        if channel is not None:
            stmt = stmt.where(EscalationTicket.contact_channel == channel.value)
        if priority is not None:
            stmt = stmt.where(EscalationTicket.priority == priority.value)

        result = await self._session.execute(stmt)
        return [EscalationTicketResponse.model_validate(t, from_attributes=True) for t in result.scalars().all()]

    async def resolve_ticket(
        self, ticket_id: UUID, *, resolution_notes: str, resolved_by: str | None
    ) -> EscalationTicketResponse:
        ticket = await self._session.get(EscalationTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(f"Ticket {ticket_id} no encontrado")
        if ticket.status == EscalationStatus.RESOLVED.value:
            raise InvalidStateTransitionError(f"El ticket {ticket_id} ya esta resuelto")

        ticket.status = EscalationStatus.RESOLVED.value
        ticket.resolution_notes = resolution_notes
        ticket.resolved_by = resolved_by
        ticket.resolved_at = datetime.now(UTC)

        await self._session.flush()
        await self._session.refresh(ticket)
        return EscalationTicketResponse.model_validate(ticket, from_attributes=True)
