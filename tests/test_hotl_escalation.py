"""Ciclo HOTL completo: a nivel de servicio (creacion/listado/resolucion de
tickets sobre Postgres real) y a nivel de grafo (derivacion -> captura de
contacto en 2 turnos -> ticket persistido)."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph import build_graph
from app.core.exceptions import InvalidStateTransitionError, TicketNotFoundError
from app.domain.models import (
    ContactChannel,
    EscalationPriority,
    EscalationStatus,
    EscalationType,
)
from app.schemas.agents import ContactCapture
from app.schemas.chat import MessageDTO
from app.services.escalation_service import EscalationService


class _StubPromptManager:
    async def get_prompt(self, agent_id: str) -> str:
        return f"prompt de prueba para {agent_id}"


class _StubSettings:
    STRUCTURED_OUTPUT_MAX_ATTEMPTS = 1
    MAX_SUPERVISOR_ITERATIONS = 0  # fuerza escalamiento desde el primer turno
    GRAPH_RECURSION_LIMIT = 25
    ESCALATION_HISTORY_WINDOW = 10


async def test_create_and_get_ticket(db_session):
    service = EscalationService(db_session)
    ticket = await service.create_ticket(
        thread_id="thread-1",
        original_question="¿Cuando cierra la inscripcion a finales?",
        relevant_history=[MessageDTO(role="human", content="¿Cuando cierra la inscripcion a finales?")],
        reason="No se encontro en la base documental",
        escalation_type=EscalationType.NO_INFO_FOUND,
        contact_channel=ContactChannel.EMAIL,
        contact_value="estudiante@ejemplo.edu",
    )
    assert ticket.status == EscalationStatus.PENDING
    assert ticket.priority == EscalationPriority.MEDIUM

    fetched = await service.get_ticket(ticket.ticket_id)
    assert fetched.original_question == ticket.original_question


async def test_max_loops_exceeded_gets_high_priority(db_session):
    service = EscalationService(db_session)
    ticket = await service.create_ticket(
        thread_id="thread-2",
        original_question="pregunta dificil",
        relevant_history=[],
        reason="limite de intentos",
        escalation_type=EscalationType.MAX_LOOPS_EXCEEDED,
        contact_channel=ContactChannel.WHATSAPP,
        contact_value="+5491100000000",
        priority=EscalationPriority.HIGH,
    )
    assert ticket.priority == EscalationPriority.HIGH


async def test_resolve_ticket_updates_status(db_session):
    service = EscalationService(db_session)
    ticket = await service.create_ticket(
        thread_id="thread-3",
        original_question="pregunta",
        relevant_history=[],
        reason="motivo",
        escalation_type=EscalationType.LOW_CONFIDENCE,
        contact_channel=ContactChannel.EMAIL,
        contact_value="x@x.com",
    )
    resolved = await service.resolve_ticket(
        ticket.ticket_id, resolution_notes="Resuelto por Secretaria", resolved_by="operador1"
    )
    assert resolved.status == EscalationStatus.RESOLVED
    assert resolved.resolved_at is not None


async def test_resolve_twice_raises_conflict(db_session):
    service = EscalationService(db_session)
    ticket = await service.create_ticket(
        thread_id="thread-4",
        original_question="pregunta",
        relevant_history=[],
        reason="motivo",
        escalation_type=EscalationType.LOW_CONFIDENCE,
        contact_channel=ContactChannel.EMAIL,
        contact_value="x@x.com",
    )
    await service.resolve_ticket(ticket.ticket_id, resolution_notes="ok", resolved_by="op1")
    with pytest.raises(InvalidStateTransitionError):
        await service.resolve_ticket(ticket.ticket_id, resolution_notes="otra vez", resolved_by="op2")


async def test_get_missing_ticket_raises_not_found(db_session):
    service = EscalationService(db_session)
    with pytest.raises(TicketNotFoundError):
        await service.get_ticket(uuid4())


async def test_list_tickets_filters_by_status(db_session):
    service = EscalationService(db_session)
    await service.create_ticket(
        thread_id="thread-5",
        original_question="q1",
        relevant_history=[],
        reason="r1",
        escalation_type=EscalationType.NO_INFO_FOUND,
        contact_channel=ContactChannel.EMAIL,
        contact_value="a@a.com",
    )
    pending = await service.list_tickets(status=EscalationStatus.PENDING)
    assert all(t.status == EscalationStatus.PENDING for t in pending)
    assert len(pending) >= 1


async def test_full_escalation_flow_creates_ticket(fake_llm, new_thread_id, db_session):
    """Grafo completo: turno 1 escala por limite de intentos y pide
    contacto; turno 2 el usuario lo comparte y el ticket queda en Postgres."""
    escalation_service = EscalationService(db_session)
    graph = build_graph(MemorySaver())

    def config() -> dict:
        return {
            "configurable": {
                "thread_id": new_thread_id,
                "llm_client": fake_llm,
                "prompt_manager": _StubPromptManager(),
                "rag_tool": AsyncMock(),
                "academic_tools": [],
                "escalation_service": escalation_service,
                "settings": _StubSettings(),
            },
            "recursion_limit": 25,
        }

    result_1 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="pregunta sin respuesta")],
            "thread_id": new_thread_id,
            "original_question": "pregunta sin respuesta",
            "iteration_count": 0,
        },
        config=config(),
    )
    assert result_1["escalation_contact_pending"] is True
    assert result_1.get("escalation_ticket_id") is None

    fake_llm.program_structured(
        ContactCapture,
        ContactCapture(is_complete=True, contact_channel=ContactChannel.EMAIL, contact_value="estudiante@uni.edu"),
    )
    result_2 = await graph.ainvoke(
        {"messages": [HumanMessage(content="estudiante@uni.edu")], "thread_id": new_thread_id, "iteration_count": 0},
        config=config(),
    )

    assert result_2["escalation_ticket_id"] is not None
    ticket = await escalation_service.get_ticket(result_2["escalation_ticket_id"])
    assert ticket.contact_value == "estudiante@uni.edu"
    assert ticket.original_question == "pregunta sin respuesta"
    assert ticket.escalation_type == EscalationType.MAX_LOOPS_EXCEEDED
