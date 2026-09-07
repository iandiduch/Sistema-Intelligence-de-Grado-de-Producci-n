"""Providers de FastAPI. Lo caro/compartido (engine, pools, clientes, grafo
compilado) vive en request.app.state.*, poblado una unica vez en el lifespan;
lo barato/por-request se construye aca. Nada de singletons globales mutables."""

from typing import Annotated, Any

from fastapi import Depends, Request
from langgraph.graph.state import CompiledStateGraph
from opentelemetry import trace
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import get_current_api_key
from app.db.models_orm import ApiKey
from app.db.session import get_db_session
from app.domain.protocols import AcademicClientProtocol
from app.services.api_key_service import ApiKeyService
from app.services.escalation_service import EscalationService
from app.services.prompt_manager import PromptManager


def get_settings_dep() -> Settings:
    return get_settings()


def get_redis_client(request: Request) -> Redis:
    return request.app.state.redis_client


def get_graph(request: Request) -> CompiledStateGraph:
    return request.app.state.compiled_graph


def get_tracer() -> trace.Tracer:
    return trace.get_tracer("intelligence-system.api")


def get_llm_client(request: Request) -> Any:
    return request.app.state.llm_client


def get_rag_tool(request: Request) -> Any:
    return request.app.state.rag_tool


def get_academic_tools(request: Request) -> list[Any]:
    return request.app.state.academic_tools


def get_academic_client(request: Request) -> AcademicClientProtocol:
    return request.app.state.academic_client


def get_prompt_manager(request: Request) -> PromptManager:
    return request.app.state.prompt_manager


def get_escalation_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_db_session)]
) -> EscalationService:
    notification_service = getattr(request.app.state, "notification_service", None)
    return EscalationService(session, notification_service=notification_service)


def get_api_key_service(
    session: Annotated[AsyncSession, Depends(get_db_session)], settings: Annotated[Settings, Depends(get_settings_dep)]
) -> ApiKeyService:
    return ApiKeyService(session, settings)


ApiKeyRecordDep = Annotated[ApiKey, Depends(get_current_api_key)]
ApiKeyServiceDep = Annotated[ApiKeyService, Depends(get_api_key_service)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
RedisDep = Annotated[Redis, Depends(get_redis_client)]
GraphDep = Annotated[CompiledStateGraph, Depends(get_graph)]
TracerDep = Annotated[trace.Tracer, Depends(get_tracer)]
LLMClientDep = Annotated[Any, Depends(get_llm_client)]
RagToolDep = Annotated[Any, Depends(get_rag_tool)]
AcademicToolsDep = Annotated[list[Any], Depends(get_academic_tools)]
AcademicClientDep = Annotated[AcademicClientProtocol, Depends(get_academic_client)]
PromptManagerDep = Annotated[PromptManager, Depends(get_prompt_manager)]
EscalationServiceDep = Annotated[EscalationService, Depends(get_escalation_service)]
