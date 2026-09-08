"""Supervisor: solo enrutamiento y coordinacion, nunca logica de
negocio completa. La decision sale siempre de SupervisorDecision via structured
output -- el unico fallback determinista es por FALLO TECNICO del LLM (timeout,
reintentos agotados), nunca una politica de negocio paralela que pueda divergir
del prompt (ese fue el anti-patron encontrado en un repo anterior).

Protege contra loops infinitos como capa 1 (capa 2 es el recursion_limit nativo
de LangGraph, pasado en el config de cada invocacion desde la capa API)."""

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import MultiAgentState
from app.core.metrics import AGENT_EXECUTIONS_TOTAL
from app.core.structured_output import invoke_structured_with_retry
from app.core.tracing_utils import agent_span
from app.domain.models import AgentRole, ConfidenceLevel, EscalationType
from app.schemas.agents import SupervisorDecision, ValidatorOutput

logger = logging.getLogger(__name__)

_DEFAULT_CLOSING_REPLY = "¡Listo! Si necesitas algo mas, avisame."


async def supervisor_node(state: MultiAgentState, config: RunnableConfig) -> dict[str, Any]:
    configurable = config["configurable"]
    settings = configurable["settings"]

    if state.get("escalation_contact_pending"):
        # graph.ainvoke() siempre reingresa por este nodo (es el entry
        # point) aunque el checkpoint venga de un turno anterior -- si ya le
        # pedimos el contacto al usuario, este turno es su respuesta y va
        # directo a escalation_agent sin volver a consultar al LLM de ruteo.
        return {"next_agent": "escalation_agent", "iteration_count": 0}

    iteration = state.get("iteration_count", 0)
    if iteration >= settings.MAX_SUPERVISOR_ITERATIONS:
        logger.warning("supervisor.max_iterations_reached", extra={"thread_id": state["thread_id"]})
        return _force_escalation(
            "Se alcanzo el limite de intentos automaticos sin resolver la consulta.",
            EscalationType.MAX_LOOPS_EXCEEDED,
        )

    llm = configurable["llm_client"]
    prompt_manager = configurable["prompt_manager"]
    system_prompt = await prompt_manager.get_prompt(AgentRole.SUPERVISOR.value)

    AGENT_EXECUTIONS_TOTAL.labels(agent_name=AgentRole.SUPERVISOR.value).inc()

    with agent_span("supervisor.route", thread_id=state["thread_id"], agent=AgentRole.SUPERVISOR) as span:
        try:
            decision = await invoke_structured_with_retry(
                llm, SupervisorDecision, system_prompt, state["messages"], settings.STRUCTURED_OUTPUT_MAX_ATTEMPTS
            )
        except Exception as exc:  # noqa: BLE001 - Fallback de resiliencia del supervisor ante fallos del LLM de ruteo
            logger.error("supervisor.llm_decision_failed", extra={"thread_id": state["thread_id"], "error": str(exc)})
            span.set_attribute("supervisor.decision", "escalation_agent")
            span.set_attribute("supervisor.reasoning", f"fallo_tecnico: {exc}")
            return _force_escalation(
                f"Fallo tecnico del supervisor al decidir el ruteo: {exc}", EscalationType.REQUIRES_HUMAN_ACTION
            )

        span.set_attribute("supervisor.decision", decision.next_agent)
        span.set_attribute("supervisor.reasoning", decision.reasoning)

    if decision.next_agent == "__end__":
        reply = decision.direct_reply or _DEFAULT_CLOSING_REPLY
        return {
            "next_agent": "__end__",
            "final_answer": reply,
            "messages": [AIMessage(content=reply, name=AgentRole.SUPERVISOR.value)],
            "iteration_count": 1,
        }

    if decision.next_agent == "escalation_agent":
        return _force_escalation(decision.reasoning, EscalationType.USER_REQUESTED)

    updates: dict[str, Any] = {"next_agent": decision.next_agent, "iteration_count": 1}
    val = state.get("validation_result")
    if val is None or not getattr(val, "requiere_mas_info", False):
        updates["knowledge_result"] = None
        updates["academic_result"] = None
        updates["validation_result"] = None
    return updates


def _force_escalation(reason: str, escalation_type: EscalationType) -> dict[str, Any]:
    return {
        "next_agent": "escalation_agent",
        "validation_result": ValidatorOutput(
            es_suficiente=False,
            requiere_mas_info=False,
            confianza=ConfidenceLevel.NOT_FOUND,
            razon=reason,
            escalation_type=escalation_type,
        ),
        "iteration_count": 1,
    }
