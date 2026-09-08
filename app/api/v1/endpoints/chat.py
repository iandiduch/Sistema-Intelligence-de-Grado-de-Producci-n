"""POST /chat y /chat/stream. thread_id lo genera esta capa (uuid4) si el
cliente no manda uno; se reutiliza en turnos siguientes y nunca se regenera
dentro del grafo."""

import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError

from app.api.dependencies import (
    AcademicToolsDep,
    EscalationServiceDep,
    GraphDep,
    LLMClientDep,
    PromptManagerDep,
    RagToolDep,
    SettingsDep,
)
from app.core.exceptions import ConversationLoopLimitError
from app.domain.models import AgentRole
from app.schemas.chat import ChatRequest, ChatResponse, RetrievalSource, StreamChunk

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Turno de conversación con el sistema multi-agente",
    description="Procesa una consulta estudiantil a través del grafo LangGraph (Supervisor, Agente RAG, Agente Académico, Validador y Escalamiento HOTL) manteniendo el contexto conversacional por `thread_id`.",
    response_description="Respuesta procesada por el agente especialista o derivación HOTL.",
)
async def chat(
    payload: ChatRequest,
    graph: GraphDep,
    llm_client: LLMClientDep,
    prompt_manager: PromptManagerDep,
    rag_tool: RagToolDep,
    academic_tools: AcademicToolsDep,
    escalation_service: EscalationServiceDep,
    settings: SettingsDep,
) -> ChatResponse:
    thread_id = payload.thread_id or str(uuid4())
    config = _build_config(
        thread_id, llm_client, prompt_manager, rag_tool, academic_tools, escalation_service, settings
    )
    graph_input = _build_input(payload, thread_id)

    try:
        result = await graph.ainvoke(graph_input, config=config)
    except GraphRecursionError as exc:
        raise ConversationLoopLimitError(f"Se alcanzo el limite de pasos del grafo: {exc}") from exc

    ticket_id = result.get("escalation_ticket_id")
    return ChatResponse(
        thread_id=thread_id,
        message=_extract_response_text(result),
        agent=_final_agent(result),
        escalated=bool(ticket_id),
        escalation_ticket_id=ticket_id,
        sources=_extract_sources(result),
    )


@router.post(
    "/chat/stream",
    summary="Conversación en streaming (Server-Sent Events)",
    description="Transmite la respuesta del grafo multi-agente token por token mediante Server-Sent Events (SSE), indicando qué agente generó cada fragmento.",
)
async def chat_stream(
    payload: ChatRequest,
    graph: GraphDep,
    llm_client: LLMClientDep,
    prompt_manager: PromptManagerDep,
    rag_tool: RagToolDep,
    academic_tools: AcademicToolsDep,
    escalation_service: EscalationServiceDep,
    settings: SettingsDep,
) -> StreamingResponse:
    thread_id = payload.thread_id or str(uuid4())
    config = _build_config(
        thread_id, llm_client, prompt_manager, rag_tool, academic_tools, escalation_service, settings
    )
    graph_input = _build_input(payload, thread_id)

    async def event_source():
        try:
            async for chunk, metadata in graph.astream(graph_input, config=config, stream_mode="messages"):
                content = getattr(chunk, "content", None)
                if not content:
                    continue
                node_name = metadata.get("langgraph_node") if isinstance(metadata, dict) else None
                stream_chunk = StreamChunk(thread_id=thread_id, delta=str(content), agent=_safe_agent(node_name))
                yield f"data: {stream_chunk.model_dump_json()}\n\n"
            yield f"data: {StreamChunk(thread_id=thread_id, delta='', done=True).model_dump_json()}\n\n"
        except GraphRecursionError as exc:
            logger.error("chat_stream.recursion_limit", extra={"thread_id": thread_id, "error": str(exc)})
            yield "event: error\ndata: se alcanzo el limite de pasos del grafo\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


def _build_config(
    thread_id: str,
    llm_client: Any,
    prompt_manager: Any,
    rag_tool: Any,
    academic_tools: list[Any],
    escalation_service: Any,
    settings: Any,
) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": thread_id,
            "llm_client": llm_client,
            "prompt_manager": prompt_manager,
            "rag_tool": rag_tool,
            "academic_tools": academic_tools,
            "escalation_service": escalation_service,
            "settings": settings,
        },
        "recursion_limit": settings.GRAPH_RECURSION_LIMIT,
    }


def _build_input(payload: ChatRequest, thread_id: str) -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content=payload.message)],
        "thread_id": thread_id,
        "original_question": payload.message,
        "iteration_count": 0,
    }


def _extract_response_text(result: dict[str, Any]) -> str:
    # final_answer solo lo setean validator (respuesta suficiente), el
    # supervisor (cierre __end__) y escalation_agent (ticket ya creado). En
    # los turnos intermedios de HOTL (pidiendo o re-pidiendo el contacto) la
    # unica respuesta real esta en el ultimo mensaje, no en final_answer.
    final_answer = result.get("final_answer")
    if final_answer:
        return final_answer
    messages = result.get("messages") or []
    if messages:
        content = getattr(messages[-1], "content", None)
        if content:
            return str(content)
    return "No se pudo generar una respuesta en este turno."


def _extract_sources(result: dict[str, Any]) -> list[RetrievalSource]:
    knowledge_result = result.get("knowledge_result")
    if knowledge_result is None:
        return []
    return [
        RetrievalSource(document_id=ref.chunk_id, filename=ref.fuente, page=ref.page)
        for ref in knowledge_result.referencias
    ]


def _final_agent(result: dict[str, Any]) -> AgentRole:
    messages = result.get("messages") or []
    if messages:
        last_name = getattr(messages[-1], "name", None)
        if last_name:
            try:
                return AgentRole(last_name)
            except ValueError:
                pass
    return AgentRole.SUPERVISOR


def _safe_agent(node_name: str | None) -> AgentRole | None:
    if node_name is None:
        return None
    try:
        return AgentRole(node_name)
    except ValueError:
        return None
