"""Nodo de escalamiento HOTL: captura contacto en 2 turnos conversacionales
usando el checkpointer normal (sin interrupt() -- HOTL es asincrono, no HITL
sincrono: el grafo llega a END en el mismo turno y la resolucion humana pasa
por los endpoints /escalations en una request posterior) y registra el
ticket via escalation_service."""

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import MultiAgentState
from app.agents.tools.escalation_tools import registrar_ticket_escalamiento
from app.core.metrics import AGENT_EXECUTIONS_TOTAL
from app.core.structured_output import invoke_structured_with_retry
from app.core.tracing_utils import hotl_escalation_span
from app.domain.models import AgentRole, EscalationType
from app.schemas.agents import ContactCapture
from app.schemas.chat import MessageDTO

logger = logging.getLogger(__name__)

_ASK_CONTACT_MESSAGE = (
    "No encontre esa informacion por los canales automaticos. "
    "Para derivarlo a Secretaria, ¿me pasas un email o un numero de WhatsApp de contacto?"
)
_RETRY_CONTACT_MESSAGE = "No pude identificar un email o un WhatsApp valido ahi. ¿Lo repetis, por favor?"


async def escalation_agent_node(state: MultiAgentState, config: RunnableConfig) -> dict[str, Any]:
    if not state.get("escalation_contact_pending"):
        return {
            "messages": [AIMessage(content=_ASK_CONTACT_MESSAGE, name=AgentRole.ESCALATION.value)],
            "escalation_contact_pending": True,
        }

    configurable = config["configurable"]
    llm = configurable["llm_client"]
    prompt_manager = configurable["prompt_manager"]
    escalation_service = configurable["escalation_service"]
    settings = configurable["settings"]

    AGENT_EXECUTIONS_TOTAL.labels(agent_name=AgentRole.ESCALATION.value).inc()

    system_prompt = await prompt_manager.get_prompt(AgentRole.ESCALATION.value)
    last_user_message = state["messages"][-1]

    try:
        capture = await invoke_structured_with_retry(
            llm, ContactCapture, system_prompt, [last_user_message], settings.STRUCTURED_OUTPUT_MAX_ATTEMPTS
        )
    except Exception as exc:  # noqa: BLE001 - Resguardo si el extractor de contacto falla; solicita reintento amablemente
        logger.error("escalation_agent.capture_failed", extra={"thread_id": state["thread_id"], "error": str(exc)})
        capture = ContactCapture(is_complete=False)

    if not capture.is_complete or capture.contact_channel is None or capture.contact_value is None:
        return {"messages": [AIMessage(content=_RETRY_CONTACT_MESSAGE, name=AgentRole.ESCALATION.value)]}

    escalation_type, reason = _escalation_context(state)
    window = state["messages"][-settings.ESCALATION_HISTORY_WINDOW :]
    relevant_history = [MessageDTO(role=m.type, content=str(m.content)) for m in window]

    with hotl_escalation_span(
        thread_id=state["thread_id"],
        ticket_id="pending",
        reason=reason,
        priority="MEDIUM",
        contact_channel=capture.contact_channel.value,
    ) as span:
        ticket = await registrar_ticket_escalamiento(
            escalation_service,
            thread_id=state["thread_id"],
            original_question=state["original_question"],
            relevant_history=relevant_history,
            reason=reason,
            escalation_type=escalation_type,
            contact_channel=capture.contact_channel,
            contact_value=capture.contact_value,
        )
        span.set_attribute("hotl.ticket_id", str(ticket.ticket_id))

    confirmation = (
        f"Listo, derive tu consulta a Secretaria (ticket {ticket.ticket_id}). "
        "Te van a contactar a la brevedad. ¿Hay algo mas en que te pueda ayudar mientras tanto?"
    )
    return {
        "escalation_ticket_id": str(ticket.ticket_id),
        "escalation_contact_pending": False,
        "final_answer": confirmation,
        "messages": [AIMessage(content=confirmation, name=AgentRole.ESCALATION.value)],
    }


def _escalation_context(state: MultiAgentState) -> tuple[EscalationType, str]:
    validation = state.get("validation_result")
    if validation is not None and validation.escalation_type is not None:
        return validation.escalation_type, validation.razon
    return EscalationType.NO_INFO_FOUND, "No se pudo determinar el motivo especifico del escalamiento."
