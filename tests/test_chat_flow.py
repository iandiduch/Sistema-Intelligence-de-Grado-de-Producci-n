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


async def test_escalation_natural_language_decline_cancels_cleanly(fake_llm, new_thread_id):
    from app.schemas.agents import ContactCapture, ContactIntent

    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="escalation_agent", reasoning="usuario solicita hablar con una persona"),
    )
    graph = build_graph(MemorySaver())
    config = _config(fake_llm, new_thread_id, [])

    # Turno 1: Entra a HOTL y solicita contacto
    result_1 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="Quiero hablar con una persona")],
            "thread_id": new_thread_id,
            "original_question": "Quiero hablar con una persona",
            "iteration_count": 0,
        },
        config=config,
    )
    assert result_1["escalation_contact_pending"] is True

    # Turno 2: El usuario declina en lenguaje natural ("no quiero")
    fake_llm.program_structured(
        ContactCapture,
        ContactCapture(is_complete=False, intent=ContactIntent.DECLINE),
    )
    result_2 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="no quiero")],
            "thread_id": new_thread_id,
            "original_question": "no quiero",
            "iteration_count": 0,
        },
        config=config,
    )
    assert result_2["escalation_contact_pending"] is False
    assert result_2.get("escalation_ticket_id") is None
    assert "cancelamos la derivación" in result_2["final_answer"].lower()


async def test_multiturn_chat_updates_original_question(fake_llm, new_thread_id):
    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="knowledge_agent", reasoning="pregunta 1"),
        SupervisorDecision(next_agent="knowledge_agent", reasoning="pregunta 2"),
    )
    fake_llm.program_structured(
        KnowledgeAgentOutput,
        KnowledgeAgentOutput(
            encontrado_en_contexto=True, nivel_de_confianza=ConfidenceLevel.HIGH, respuesta="r1", referencias=[]
        ),
        KnowledgeAgentOutput(
            encontrado_en_contexto=True, nivel_de_confianza=ConfidenceLevel.HIGH, respuesta="r2", referencias=[]
        ),
    )
    fake_llm.program_structured(
        ValidatorOutput,
        ValidatorOutput(
            es_suficiente=True,
            requiere_mas_info=False,
            confianza=ConfidenceLevel.HIGH,
            razon="ok",
            respuesta_sintetizada="r1",
        ),
        ValidatorOutput(
            es_suficiente=True,
            requiere_mas_info=False,
            confianza=ConfidenceLevel.HIGH,
            razon="ok",
            respuesta_sintetizada="r2",
        ),
    )

    graph = build_graph(MemorySaver())
    config = _config(fake_llm, new_thread_id, [{"text": "info", "metadata": {"source": "doc.pdf"}}])

    # Turno 1
    r1 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="¿Cómo son las equivalencias?")],
            "thread_id": new_thread_id,
            "original_question": "¿Cómo son las equivalencias?",
            "iteration_count": 0,
        },
        config=config,
    )
    assert r1["original_question"] == "¿Cómo son las equivalencias?"

    # Turno 2 (Mismo thread_id, pregunta completamente distinta)
    r2 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="¿Por quién están integrados los departamentos?")],
            "thread_id": new_thread_id,
            "original_question": "¿Por quién están integrados los departamentos?",
            "iteration_count": 0,
        },
        config=config,
    )
    assert r2["original_question"] == "¿Por quién están integrados los departamentos?"
    assert r2["final_answer"] == "r2"


async def test_multiturn_chat_after_ticket_creation_resets_and_answers_new_question(fake_llm, new_thread_id):
    """Verifica que tras derivar y registrar un ticket HOTL, el siguiente mensaje en el mismo
    thread no mantenga acumulado el contador de iteraciones ni vuelva a escalar a ciegas."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.domain.models import ContactChannel, EscalationPriority, EscalationStatus, EscalationType
    from app.schemas.agents import ContactCapture
    from app.schemas.escalation import EscalationTicketResponse

    # Mock del servicio de escalamiento para retornar un ticket válido
    mock_ticket = EscalationTicketResponse(
        ticket_id=uuid4(),
        thread_id=new_thread_id,
        original_question="¿pregunta 1?",
        relevant_history=[],
        reason="no_info",
        escalation_type=EscalationType.NO_INFO_FOUND,
        priority=EscalationPriority.MEDIUM,
        contact_channel=ContactChannel.EMAIL,
        contact_value="test@alumno.edu",
        status=EscalationStatus.PENDING,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_escalation = AsyncMock()
    mock_escalation.create_ticket = AsyncMock(return_value=mock_ticket)

    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="escalation_agent", reasoning="no se encontro respuesta inicial"),
    )
    fake_llm.program_structured(
        ContactCapture,
        ContactCapture(is_complete=True, contact_channel=ContactChannel.EMAIL, contact_value="test@alumno.edu"),
    )

    graph = build_graph(MemorySaver())
    config = _config(fake_llm, new_thread_id, [])
    config["configurable"]["escalation_service"] = mock_escalation

    # Turno 1: Entra a escalamiento y solicita contacto
    r1 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="¿Cómo rindo libre?")],
            "thread_id": new_thread_id,
            "original_question": "¿Cómo rindo libre?",
            "iteration_count": 0,
        },
        config=config,
    )
    assert r1["escalation_contact_pending"] is True

    # Turno 2: El usuario provee su email -> se crea el ticket
    r2 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="test@alumno.edu")],
            "thread_id": new_thread_id,
            "original_question": "test@alumno.edu",
            "iteration_count": 0,
        },
        config=config,
    )
    assert r2["escalation_contact_pending"] is False
    assert r2["escalation_ticket_id"] == str(mock_ticket.ticket_id)

    # Turno 3: Mismo thread_id -> el usuario realiza una nueva pregunta académica
    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="knowledge_agent", reasoning="consulta institucional sobre requisitos"),
    )
    fake_llm.program_structured(
        KnowledgeAgentOutput,
        KnowledgeAgentOutput(
            encontrado_en_contexto=True,
            nivel_de_confianza=ConfidenceLevel.HIGH,
            respuesta="Tener regularidad y correlativas aprobadas.",
            referencias=[],
        ),
    )
    fake_llm.program_structured(
        ValidatorOutput,
        ValidatorOutput(
            es_suficiente=True,
            requiere_mas_info=False,
            confianza=ConfidenceLevel.HIGH,
            razon="responde adecuadamente",
            respuesta_sintetizada="Tener regularidad y correlativas aprobadas.",
        ),
    )

    r3 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="que requisitos para rendir como regular hay ?")],
            "thread_id": new_thread_id,
            "original_question": "que requisitos para rendir como regular hay ?",
            "iteration_count": 0,
            "escalation_ticket_id": None,
        },
        config=config,
    )

    assert r3["final_answer"] == "Tener regularidad y correlativas aprobadas."
    assert r3["iteration_count"] == 1
    assert r3["escalation_contact_pending"] is False
    assert r3.get("escalation_ticket_id") is None


async def test_escalation_new_query_intent_transitions_to_supervisor_and_resolves(fake_llm, new_thread_id):
    """Verifica que si el bot está esperando datos de contacto y el usuario hace una nueva
    pregunta temática, el agente de escalamiento la reconozca como new_query, cancele el
    escalamiento y transicione inmediatamente al supervisor para responderla en el mismo turno."""
    from app.schemas.agents import ContactCapture, ContactIntent

    # Turno 1: Entra a escalamiento y pide contacto
    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="escalation_agent", reasoning="no se encontró"),
    )
    graph = build_graph(MemorySaver())
    config = _config(fake_llm, new_thread_id, [{"text": "info", "metadata": {"source": "reglamento.pdf"}}])

    r1 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="¿Cómo rindo libre?")],
            "thread_id": new_thread_id,
            "original_question": "¿Cómo rindo libre?",
            "iteration_count": 0,
        },
        config=config,
    )
    assert r1["escalation_contact_pending"] is True

    # Turno 2: En vez de dar contacto o decir "no", el usuario hace una NUEVA pregunta temática
    fake_llm.program_structured(
        ContactCapture,
        ContactCapture(is_complete=False, intent=ContactIntent.NEW_QUERY),
    )
    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="knowledge_agent", reasoning="nueva pregunta sobre inscripción"),
    )
    fake_llm.program_structured(
        KnowledgeAgentOutput,
        KnowledgeAgentOutput(
            encontrado_en_contexto=True,
            nivel_de_confianza=ConfidenceLevel.HIGH,
            respuesta="Las inscripciones a finales cierran 72 horas antes.",
            referencias=[],
        ),
    )
    fake_llm.program_structured(
        ValidatorOutput,
        ValidatorOutput(
            es_suficiente=True,
            requiere_mas_info=False,
            confianza=ConfidenceLevel.HIGH,
            razon="responde adecuadamente",
            respuesta_sintetizada="Las inscripciones a finales cierran 72 horas antes.",
        ),
    )

    r2 = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="hasta cuando me puedo inscribir en un final ?")],
            "thread_id": new_thread_id,
            "original_question": "hasta cuando me puedo inscribir en un final ?",
            "iteration_count": 0,
            "escalation_ticket_id": None,
        },
        config=config,
    )

    # Debe haber respondido la nueva pregunta directamente sin pedir email/whatsapp de nuevo
    assert r2["final_answer"] == "Las inscripciones a finales cierran 72 horas antes."
    assert r2["escalation_contact_pending"] is False
    assert r2.get("escalation_ticket_id") is None


