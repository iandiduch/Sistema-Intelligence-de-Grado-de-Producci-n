"""E2E del grafo: Supervisor -> Agente especialista -> Validador -> Respuesta,
con un FakeLLM que reemplaza las llamadas reales a OpenAI (deterministico,
sin costo ni credenciales). No requiere Postgres real: usa MemorySaver."""

from unittest.mock import AsyncMock

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph import build_graph
from app.domain.models import ConfidenceLevel
from app.schemas.agents import AcademicAgentOutput, KnowledgeAgentOutput, SupervisorDecision, ValidatorOutput


class _StubPromptManager:
    async def get_prompt(self, agent_id: str) -> str:
        return f"prompt de prueba para {agent_id}"


class _StubSettings:
    STRUCTURED_OUTPUT_MAX_ATTEMPTS = 1
    MAX_SUPERVISOR_ITERATIONS = 6
    GRAPH_RECURSION_LIMIT = 25
    ESCALATION_HISTORY_WINDOW = 10


def _config(fake_llm: object, thread_id: str, rag_chunks: list[dict]) -> dict:
    rag_tool = AsyncMock()
    rag_tool.ainvoke = AsyncMock(return_value=rag_chunks)
    return {
        "configurable": {
            "thread_id": thread_id,
            "llm_client": fake_llm,
            "prompt_manager": _StubPromptManager(),
            "rag_tool": rag_tool,
            "academic_tools": [],
            "escalation_service": AsyncMock(),
            "settings": _StubSettings(),
        },
        "recursion_limit": 25,
    }


async def test_chat_flow_resolves_via_knowledge_agent(fake_llm, new_thread_id):
    # Con la optimización directa (Agent -> Validator), el supervisor solo se visita
    # UNA vez para enrutar a knowledge_agent. El validador se ejecuta automáticamente.
    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="knowledge_agent", reasoning="pregunta institucional"),
    )
    fake_llm.program_structured(
        KnowledgeAgentOutput,
        KnowledgeAgentOutput(
            encontrado_en_contexto=True,
            nivel_de_confianza=ConfidenceLevel.HIGH,
            respuesta="La inscripcion cierra el 15 de marzo.",
            referencias=[],
        ),
    )
    fake_llm.program_structured(
        ValidatorOutput,
        ValidatorOutput(
            es_suficiente=True,
            requiere_mas_info=False,
            confianza=ConfidenceLevel.HIGH,
            razon="la respuesta contesta lo preguntado",
            respuesta_sintetizada="La inscripcion cierra el 15 de marzo.",
        ),
    )

    graph = build_graph(MemorySaver())
    config = _config(fake_llm, new_thread_id, [{"text": "info", "metadata": {"source": "reglamento.pdf", "page": 3}}])

    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="¿Cuando cierra la inscripcion?")],
            "thread_id": new_thread_id,
            "original_question": "¿Cuando cierra la inscripcion?",
            "iteration_count": 0,
        },
        config=config,
    )

    assert result["final_answer"] == "La inscripcion cierra el 15 de marzo."
    assert result.get("escalation_ticket_id") is None


async def test_chat_flow_greeting_ends_immediately(fake_llm, new_thread_id):
    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="__end__", reasoning="saludo", direct_reply="¡Hola! ¿En que te puedo ayudar?"),
    )

    graph = build_graph(MemorySaver())
    config = _config(fake_llm, new_thread_id, [])

    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="hola")],
            "thread_id": new_thread_id,
            "original_question": "hola",
            "iteration_count": 0,
        },
        config=config,
    )

    assert result["final_answer"] == "¡Hola! ¿En que te puedo ayudar?"


async def test_supervisor_forces_escalation_after_max_iterations(fake_llm, new_thread_id):
    graph = build_graph(MemorySaver())
    config = _config(fake_llm, new_thread_id, [])
    config["configurable"]["settings"] = type("S", (_StubSettings,), {"MAX_SUPERVISOR_ITERATIONS": 0})()

    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="pregunta imposible")],
            "thread_id": new_thread_id,
            "original_question": "pregunta imposible",
            "iteration_count": 0,
        },
        config=config,
    )

    # con MAX_SUPERVISOR_ITERATIONS=0 el limite se alcanza en el primer paso,
    # sin necesitar ninguna respuesta programada del FakeLLM.
    assert result["escalation_contact_pending"] is True
    assert result.get("escalation_ticket_id") is None
    last_message = result["messages"][-1].content.lower()
    assert "email" in last_message or "whatsapp" in last_message


async def test_chat_flow_multi_agent_cycle_via_validator(fake_llm, new_thread_id):
    """Verifica el ciclo multi-agente: el validador determina requiere_mas_info=True,
    devolviendo el flujo al Supervisor para convocar al especialista complementario."""
    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="knowledge_agent", reasoning="consulta institucional inicial"),
        SupervisorDecision(next_agent="academic_agent", reasoning="validador solicita info complementaria"),
    )
    fake_llm.program_structured(
        KnowledgeAgentOutput,
        KnowledgeAgentOutput(
            encontrado_en_contexto=True,
            nivel_de_confianza=ConfidenceLevel.MEDIUM,
            respuesta="El plan de estudios incluye Algoritmos.",
            referencias=[],
        ),
    )
    fake_llm.program_structured(
        AcademicAgentOutput,
        AcademicAgentOutput(
            respuesta="Algoritmos se cursa los martes de 18 a 22 hs.",
            datos={"horario": "Martes 18-22hs"},
        ),
    )
    fake_llm.program_structured(
        ValidatorOutput,
        # 1er paso de validación: falta horario
        ValidatorOutput(
            es_suficiente=False,
            requiere_mas_info=True,
            confianza=ConfidenceLevel.MEDIUM,
            razon="Falta información de horarios de cursada",
        ),
        # 2do paso de validación: completo
        ValidatorOutput(
            es_suficiente=True,
            requiere_mas_info=False,
            confianza=ConfidenceLevel.HIGH,
            razon="Se reunió la información reglamentaria y de cursada",
            respuesta_sintetizada="El plan incluye Algoritmos y se cursa los martes de 18 a 22 hs.",
        ),
    )

    graph = build_graph(MemorySaver())
    config = _config(fake_llm, new_thread_id, [{"text": "info", "metadata": {"source": "plan.pdf"}}])

    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="¿Cómo es el plan de Algoritmos y qué horario tiene?")],
            "thread_id": new_thread_id,
            "original_question": "¿Cómo es el plan de Algoritmos y qué horario tiene?",
            "iteration_count": 0,
        },
        config=config,
    )

    assert result["final_answer"] == "El plan incluye Algoritmos y se cursa los martes de 18 a 22 hs."
    assert result.get("escalation_ticket_id") is None
