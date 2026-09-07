"""Verifica que el estado de una conversacion sobrevive un 'reinicio': se
crea un checkpointer/pool NUEVO contra el mismo Postgres (en vez de
reiniciar un contenedor de verdad, que seria un test mas caro y fragil sin
ganar cobertura real) y se confirma que el thread_id sigue resolviendo el
historial acumulado."""


import pytest

from app.agents.graph import build_graph
from app.db.checkpointer import build_checkpointer, build_checkpointer_pool
from app.schemas.agents import SupervisorDecision


class _StubPromptManager:
    async def get_prompt(self, agent_id: str) -> str:
        return f"prompt de prueba para {agent_id}"


async def test_thread_state_survives_fresh_checkpointer(test_settings, fake_llm, new_thread_id):
    from langchain_core.messages import HumanMessage

    fake_llm.program_structured(
        SupervisorDecision,
        SupervisorDecision(next_agent="__end__", reasoning="saludo", direct_reply="Hola, ¿en que te ayudo?"),
    )

    try:
        pool_a = await build_checkpointer_pool(test_settings)
        checkpointer_a = build_checkpointer(pool_a)
        await checkpointer_a.setup()
    except Exception as exc:  # noqa: BLE001 - Salta test si PostgreSQL no está disponible
        pytest.skip(f"Postgres/Checkpointer no disponible ({exc}) -- levantar 'docker compose up -d postgres'")

    graph_a = build_graph(checkpointer_a)
    config = {
        "configurable": {
            "thread_id": new_thread_id,
            "llm_client": fake_llm,
            "prompt_manager": _StubPromptManager(),
            "rag_tool": None,
            "academic_tools": [],
            "escalation_service": None,
            "settings": test_settings,
        },
        "recursion_limit": test_settings.GRAPH_RECURSION_LIMIT,
    }
    await graph_a.ainvoke(
        {
            "messages": [HumanMessage(content="hola")],
            "thread_id": new_thread_id,
            "original_question": "hola",
            "iteration_count": 0,
        },
        config=config,
    )
    await pool_a.close()

    # "reinicio": pool y checkpointer nuevos, sin ningun objeto compartido
    # con la corrida anterior -- solo el mismo Postgres en disco.
    pool_b = await build_checkpointer_pool(test_settings)
    try:
        checkpointer_b = build_checkpointer(pool_b)
        graph_b = build_graph(checkpointer_b)

        snapshot = await graph_b.aget_state({"configurable": {"thread_id": new_thread_id}})
    finally:
        await pool_b.close()

    assert snapshot.values["original_question"] == "hola"
    assert snapshot.values["final_answer"] == "Hola, ¿en que te ayudo?"
    assert len(snapshot.values["messages"]) >= 2
