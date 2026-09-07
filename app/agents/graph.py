"""Topologia del grafo multi-agente. Unico lugar donde se construye -- nunca se duplica en endpoints ni servicios.

Dos edges condicionales separadas a proposito (supervisor y validator): son
ejes ortogonales -- ruteo de negocio vs. suficiencia/calidad -- fusionarlas en
una sola funcion violaria SRP y dificultaria testear cada una en aislamiento.
"""

from typing import Literal

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.specialized.academic_agent import academic_agent_node
from app.agents.specialized.escalation_agent import escalation_agent_node
from app.agents.specialized.knowledge_agent import knowledge_agent_node
from app.agents.specialized.validator_agent import validator_node
from app.agents.state import MultiAgentState
from app.agents.supervisor import supervisor_node


def route_from_supervisor(
    state: MultiAgentState,
) -> Literal["knowledge_agent", "academic_agent", "validator", "escalation_agent", "__end__"]:
    return state["next_agent"] or "__end__"


def route_from_validator(state: MultiAgentState) -> Literal["supervisor", "escalation_agent", "__end__"]:
    validation = state["validation_result"]
    if validation is None:
        return "escalation_agent"
    if validation.es_suficiente:
        return "__end__"
    if validation.requiere_mas_info:
        return "supervisor"
    return "escalation_agent"


def build_graph(checkpointer: AsyncPostgresSaver) -> CompiledStateGraph:
    builder = StateGraph(MultiAgentState)

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("knowledge_agent", knowledge_agent_node)
    builder.add_node("academic_agent", academic_agent_node)
    builder.add_node("validator", validator_node)
    builder.add_node("escalation_agent", escalation_agent_node)

    builder.set_entry_point("supervisor")
    builder.add_edge("knowledge_agent", "validator")
    builder.add_edge("academic_agent", "validator")
    builder.add_edge("escalation_agent", END)

    builder.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "knowledge_agent": "knowledge_agent",
            "academic_agent": "academic_agent",
            "validator": "validator",
            "escalation_agent": "escalation_agent",
            "__end__": END,
        },
    )
    builder.add_conditional_edges(
        "validator",
        route_from_validator,
        {"supervisor": "supervisor", "escalation_agent": "escalation_agent", "__end__": END},
    )

    return builder.compile(checkpointer=checkpointer)
