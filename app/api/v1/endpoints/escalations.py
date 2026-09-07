"""Endpoints HOTL: listado/detalle/resolucion de tickets, mas creacion
programatica directa."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import EscalationServiceDep
from app.core.security import require_scope
from app.domain.models import (
    ApiKeyScope,
    ContactChannel,
    EscalationPriority,
    EscalationStatus,
)
from app.schemas.escalation import (
    EscalationResolveRequest,
    EscalationTicketCreate,
    EscalationTicketResponse,
)

router = APIRouter()


@router.get(
    "/escalations",
    response_model=list[EscalationTicketResponse],
    summary="Listar tickets HOTL derivados a Secretaría/Bedelía",
    description="Obtiene el listado de casos que no pudieron ser resueltos automáticamente y fueron derivados para atención humana, con filtros opcionales por estado, canal o prioridad.",
    response_description="Lista paginada de tickets de soporte.",
)
async def list_escalations(
    service: EscalationServiceDep,
    status: Annotated[EscalationStatus | None, Query(description="Filtrar por estado del ticket")] = None,
    channel: Annotated[ContactChannel | None, Query(description="Filtrar por canal de contacto")] = None,
    priority: Annotated[EscalationPriority | None, Query(description="Filtrar por prioridad")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Cantidad máxima de resultados")] = 50,
    offset: Annotated[int, Query(ge=0, description="Desplazamiento para paginación")] = 0,
) -> list[EscalationTicketResponse]:
    return await service.list_tickets(status=status, channel=channel, priority=priority, limit=limit, offset=offset)


@router.get(
    "/escalations/{ticket_id}",
    response_model=EscalationTicketResponse,
    summary="Consultar detalle de un ticket HOTL",
    description="Recupera la información completa de un caso derivado: pregunta original, historial relevante de mensajes, motivo de derivación y datos de contacto del estudiante.",
    response_description="Detalle completo del ticket.",
)
async def get_escalation(ticket_id: UUID, service: EscalationServiceDep) -> EscalationTicketResponse:
    return await service.get_ticket(ticket_id)


@router.post(
    "/escalations",
    response_model=EscalationTicketResponse,
    status_code=201,
    summary="Crear ticket HOTL programático",
    description="Permite a un operador o sistema externo registrar manualmente un ticket de derivación institucional.",
    response_description="Ticket de escalamiento creado y persistido.",
)
async def create_escalation(
    payload: EscalationTicketCreate, service: EscalationServiceDep
) -> EscalationTicketResponse:
    return await service.create_ticket(
        thread_id=payload.thread_id,
        original_question=payload.original_question,
        relevant_history=payload.relevant_history,
        reason=payload.reason,
        escalation_type=payload.escalation_type,
        contact_channel=payload.contact_channel,
        contact_value=payload.contact_value,
        priority=payload.priority,
    )


@router.post(
    "/escalations/{ticket_id}/resolve",
    response_model=EscalationTicketResponse,
    summary="Resolver ticket HOTL (Operador Humano)",
    description="Registra la respuesta y notas de resolución de un operador de Bedelía/Secretaría, cambiando el estado del ticket a RESOLVED. Requiere API Key con scope 'admin'.",
    response_description="Ticket actualizado a estado resuelto.",
    dependencies=[Depends(require_scope(ApiKeyScope.ADMIN))],
)
async def resolve_escalation(
    ticket_id: UUID, payload: EscalationResolveRequest, service: EscalationServiceDep
) -> EscalationTicketResponse:
    return await service.resolve_ticket(
        ticket_id, resolution_notes=payload.resolution_notes, resolved_by=payload.resolved_by
    )
