"""MultiAgentState: contrato central y unico del grafo. Cada
agente especializado escribe solo su propia clave -- evita condiciones de
carrera aunque la topologia de hoy sea secuencial, no paralela.

`iteration_count` usa operator.add a proposito (a diferencia de `messages`,
que usa add_messages): es un contador plano donde cada nodo devuelve el delta
a sumar, no una lista que necesite merge por id.
"""

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from app.schemas.agents import (
    AcademicAgentOutput,
    KnowledgeAgentOutput,
    ValidatorOutput,
)


def _keep_first(existing: str | None, new: str | None) -> str | None:
    """Reducer para original_question: el primer valor no vacio que llega
    en un thread queda pegado -- turnos siguientes (ej. cuando el usuario
    solo esta compartiendo su contacto para HOTL) no lo pisan."""
    return existing if existing else new


class MultiAgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    thread_id: str
    original_question: Annotated[str, _keep_first]
    next_agent: str | None
    knowledge_result: KnowledgeAgentOutput | None
    academic_result: AcademicAgentOutput | None
    validation_result: ValidatorOutput | None
    escalation_ticket_id: str | None
    escalation_contact_pending: bool
    iteration_count: Annotated[int, operator.add]
    final_answer: str | None
    error: str | None
