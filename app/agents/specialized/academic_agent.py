"""Nodo del Academic Agent: resuelve horarios/matriculacion/aula via tools
tipadas. El LLM decide que tool(s) llamar (bind_tools); alcanza con una vuelta
de tool-calling, sin necesidad de un loop ReAct multi-turno."""

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import MultiAgentState
from app.core.metrics import AGENT_EXECUTIONS_TOTAL
from app.core.structured_output import invoke_structured_with_retry
from app.core.tracing_utils import agent_span
from app.domain.models import AgentRole
from app.schemas.agents import AcademicAgentOutput

logger = logging.getLogger(__name__)


async def academic_agent_node(state: MultiAgentState, config: RunnableConfig) -> dict[str, Any]:
    configurable = config["configurable"]
    llm = configurable["llm_client"]
    prompt_manager = configurable["prompt_manager"]
    tools = configurable["academic_tools"]
    settings = configurable["settings"]

    system_prompt = await prompt_manager.get_prompt(AgentRole.ACADEMIC.value)
    tools_by_name = {t.name: t for t in tools}

    AGENT_EXECUTIONS_TOTAL.labels(agent_name=AgentRole.ACADEMIC.value).inc()

    with agent_span("academic_agent.answer", thread_id=state["thread_id"], agent=AgentRole.ACADEMIC):
        conversation = list(state["messages"])
        ai_message = await llm.bind_tools(tools).ainvoke(conversation)
        conversation.append(ai_message)

        for tool_call in ai_message.tool_calls or []:
            tool = tools_by_name.get(tool_call["name"])
            if tool is None:
                continue
            try:
                result: Any = await tool.ainvoke(tool_call["args"])
            except Exception as exc:  # noqa: BLE001 - Resguardo para que el error de tool se reporte al LLM como mensaje
                result = {"error": str(exc)}
            conversation.append(
                ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call["id"])
            )

        try:
            output = await invoke_structured_with_retry(
                llm, AcademicAgentOutput, system_prompt, conversation, settings.STRUCTURED_OUTPUT_MAX_ATTEMPTS
            )
        except Exception as exc:  # noqa: BLE001 - Fallback si el LLM de síntesis falla
            logger.error("academic_agent.llm_failed", extra={"thread_id": state["thread_id"], "error": str(exc)})
            output = AcademicAgentOutput(
                respuesta="No pude resolver la consulta academica en este momento.", datos={}
            )

    return {
        "academic_result": output,
        "messages": [AIMessage(content=output.respuesta, name=AgentRole.ACADEMIC.value)],
    }
