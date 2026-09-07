"""Helper de creacion de ticket HOTL. A proposito NO es un @tool invocable por
el LLM: una vez capturado el contacto, crear el ticket es logica determinista,
no una decision que el modelo deba tomar turno a turno."""

from app.domain.models import ContactChannel, EscalationPriority, EscalationType
from app.schemas.chat import MessageDTO
from app.schemas.escalation import EscalationTicketResponse
from app.services.escalation_service import EscalationService

_HIGH_PRIORITY_TYPES = {EscalationType.MAX_LOOPS_EXCEEDED, EscalationType.REQUIRES_HUMAN_ACTION}


async def registrar_ticket_escalamiento(
    escalation_service: EscalationService,
    *,
    thread_id: str,
    original_question: str,
    relevant_history: list[MessageDTO],
    reason: str,
    escalation_type: EscalationType,
    contact_channel: ContactChannel,
    contact_value: str,
) -> EscalationTicketResponse:
    priority = EscalationPriority.HIGH if escalation_type in _HIGH_PRIORITY_TYPES else EscalationPriority.MEDIUM
    return await escalation_service.create_ticket(
        thread_id=thread_id,
        original_question=original_question,
        relevant_history=relevant_history,
        reason=reason,
        escalation_type=escalation_type,
        contact_channel=contact_channel,
        contact_value=contact_value,
        priority=priority,
    )
