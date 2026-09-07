"""Nodo Validador: decide si knowledge_result/academic_result alcanzan para
cerrar la conversacion o si hay que escalar a HOTL. Eje ortogonal al del
Supervisor (este evalua suficiencia/calidad, el Supervisor decide ruteo de
negocio) -- por eso viven en edges condicionales separadas en graph.py."""

import logging
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import MultiAgentState
from app.core.metrics import AGENT_EXECUTIONS_TOTAL
from app.core.structured_output import invoke_structured_with_retry
from app.core.tracing_utils import agent_span
from app.domain.models import AgentRole, ConfidenceLevel, EscalationType
from app.schemas.agents import ValidatorOutput

logger = logging.getLogger(__name__)


async def validator_node(state: MultiAgentState, config: RunnableConfig) -> dict[str, Any]:
    configurable = config["configurable"]
    llm = configurable["llm_client"]
    prompt_manager = configurable["prompt_manager"]
    settings = configurable["settings"]

    system_prompt = await prompt_manager.get_prompt(AgentRole.VALIDATOR.value)
    evidence = _summarize_evidence(state)

    AGENT_EXECUTIONS_TOTAL.labels(agent_name=AgentRole.VALIDATOR.value).inc()

    with agent_span("validator.decide", thread_id=state["thread_id"], agent=AgentRole.VALIDATOR) as span:
        messages = [*state["messages"], SystemMessage(content=f"Evidencia disponible para evaluar:\n{evidence}")]
        try:
            output = await invoke_structured_with_retry(
                llm, ValidatorOutput, system_prompt, messages, settings.STRUCTURED_OUTPUT_MAX_ATTEMPTS
            )
        except Exception as exc:  # noqa: BLE001 - Fallback conservador de validación hacia HOTL ante fallo del LLM
            logger.error("validator.llm_failed", extra={"thread_id": state["thread_id"], "error": str(exc)})
            output = ValidatorOutput(
                es_suficiente=False,
                requiere_mas_info=False,
                confianza=ConfidenceLevel.NOT_FOUND,
                razon=f"Fallo tecnico del validador: {exc}",
                escalation_type=EscalationType.REQUIRES_HUMAN_ACTION,
            )

        span.set_attribute("validator.sufficient", output.es_suficiente)
        span.set_attribute("validator.confidence", output.confianza.value)

    result: dict[str, Any] = {"validation_result": output}
    if output.es_suficiente and output.respuesta_sintetizada:
        result["final_answer"] = output.respuesta_sintetizada
        result["messages"] = [AIMessage(content=output.respuesta_sintetizada, name=AgentRole.VALIDATOR.value)]
    return result


def _summarize_evidence(state: MultiAgentState) -> str:
    parts = []
    knowledge_result = state.get("knowledge_result")
    if knowledge_result is not None:
        parts.append(
            f"Conocimiento institucional -> encontrado_en_contexto={knowledge_result.encontrado_en_contexto}, "
            f"confianza={knowledge_result.nivel_de_confianza.value}, respuesta='{knowledge_result.respuesta}'"
        )
    academic_result = state.get("academic_result")
    if academic_result is not None:
        parts.append(f"Operacion academica -> respuesta='{academic_result.respuesta}', datos={academic_result.datos}")
    return "\n".join(parts) if parts else "(sin resultados de ningun agente todavia)"
