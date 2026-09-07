"""Entrypoint FastAPI: lifespan, middleware, exception handlers, routers y métricas.

Todo lo compartido y costoso de inicializar se construye UNA vez en el lifespan y vive en
`app.state` (ver app/api/dependencies.py). El worker de ingesta corre como proceso separado
(app/services/ingestion_worker.py).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_openai import ChatOpenAI
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.agents.graph import build_graph
from app.agents.tools.academic_tools import build_academic_tools
from app.agents.tools.rag_tools import build_rag_tools
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import (
    AppException,
    AuthenticationError,
    InfrastructureError,
    RateLimitExceededError,
)
from app.core.logging import configure_logging
from app.core.metrics import PrometheusMetricsMiddleware, metrics_router
from app.core.rate_limit import RateLimiter
from app.core.redis import build_redis_client
from app.core.security import require_scope
from app.core.security_headers import SecurityHeadersMiddleware
from app.core.telemetry import setup_telemetry, shutdown_telemetry
from app.db.checkpointer import build_checkpointer, build_checkpointer_pool
from app.db.session import build_engine, build_sessionmaker
from app.domain.models import ApiKeyScope
from app.services.academic_client import MockAcademicClient
from app.services.notification_service import HOTLNotificationService
from app.services.prompt_manager import PromptManager
from app.services.rag_service import (
    build_embeddings_client,
    build_pinecone_client,
    get_index,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings)
    app.state.settings = settings

    if not settings.API_KEY_PEPPER.get_secret_value():
        logger.warning("lifespan.api_key_pepper_empty", extra={"hint": "generar con: openssl rand -hex 32"})

    setup_telemetry(settings)

    engine = build_engine(settings)
    app.state.db_engine = engine
    app.state.db_sessionmaker = build_sessionmaker(engine)

    checkpointer_pool = await build_checkpointer_pool(settings)
    app.state.checkpointer_pool = checkpointer_pool
    checkpointer = build_checkpointer(checkpointer_pool)

    app.state.llm_client = ChatOpenAI(
        model=settings.OPENAI_CHAT_MODEL,
        api_key=settings.OPENAI_API_KEY.get_secret_value(),
        temperature=settings.LLM_TEMPERATURE,
    )

    app.state.pinecone_client = build_pinecone_client(settings)
    app.state.rag_index = await get_index(app.state.pinecone_client, settings)
    app.state.embeddings_client = build_embeddings_client(settings)

    # Retrieval híbrido conectado a PostgreSQL FTS (sin consumir memoria RAM del API)
    app.state.rag_tool = build_rag_tools(
        app.state.rag_index,
        app.state.embeddings_client,
        app.state.db_sessionmaker,
        settings,
    )[0]

    app.state.academic_client = MockAcademicClient()
    app.state.academic_tools = build_academic_tools(app.state.academic_client)

    app.state.prompt_manager = PromptManager(app.state.db_sessionmaker)
    app.state.notification_service = HOTLNotificationService(settings)

    app.state.compiled_graph = build_graph(checkpointer)

    redis_client = build_redis_client(settings)
    try:
        await redis_client.ping()
    except Exception as exc:  # noqa: BLE001 - Aviso no bloqueante al arranque
        logger.warning("lifespan.redis_unreachable", extra={"error": str(exc)})
    app.state.redis_client = redis_client

    rate_limiter = RateLimiter(redis_client)
    try:
        await rate_limiter.preload()
    except Exception as exc:  # noqa: BLE001 - Se reintentará bajo demanda con eval si Redis no está listo
        logger.warning("lifespan.rate_limiter_preload_skipped", extra={"error": str(exc)})
    app.state.rate_limiter = rate_limiter

    logger.info("lifespan.startup_complete")
    yield

    await app.state.redis_client.aclose()
    await app.state.rag_index.close()
    await app.state.pinecone_client.close()
    await app.state.checkpointer_pool.close()
    await app.state.db_engine.dispose()
    shutdown_telemetry()
    logger.info("lifespan.shutdown_complete")


app = FastAPI(
    title="Sistema de Inteligencia Universitario",
    description="""## Plataforma de Inteligencia Artificial para el Ámbito Universitario e Institucional

Sistema de grado de producción que integra:
* **Orquestación Multi-Agente con LangGraph**: Supervisor Router, Agentes Especialistas (Conocimiento y Académico), Validador y Escalamiento HOTL.
* **RAG Híbrido Distribuido**: Búsqueda semántica densa en Pinecone combinada con búsqueda léxica en PostgreSQL (Full-Text Search).
* **Memoria Conversacional Persistente**: Checkpointer en PostgreSQL (`AsyncPostgresSaver`) para retención de estado multi-turno.
* **Supervisión HOTL (Human-on-the-Loop)**: Captura asíncrona de datos de contacto y emisión de tickets administrativos.
* **Seguridad y Rate Limiting**: Autenticación por API Key (SHA-256 + pepper) y algoritmo *sliding window counter* en Redis.
* **Observabilidad Integral**: Trazabilidad con OpenTelemetry, OpenInference, Arize Phoenix y métricas Prometheus.
""",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/api/v1/openapi.json",
    openapi_tags=[
        {
            "name": "chat",
            "description": "Endpoints de interacción conversacional y streaming con el sistema multi-agente.",
        },
        {
            "name": "ingest",
            "description": "Carga y consulta de jobs de ingesta documental para la base de conocimiento institucional.",
        },
        {
            "name": "escalations",
            "description": "Gestión, consulta y resolución de tickets de escalamiento HOTL.",
        },
        {
            "name": "prompts",
            "description": "Inspección y actualización en caliente de directivas y system prompts de agentes.",
        },
        {
            "name": "admin",
            "description": "Administración de credenciales y claves de acceso a la API.",
        },
        {
            "name": "health",
            "description": "Diagnóstico de conectividad y estado operativo de servicios dependientes.",
        },
    ],
    lifespan=lifespan,
)

app.add_middleware(PrometheusMetricsMiddleware)
app.include_router(
    metrics_router,
    dependencies=[Depends(require_scope(ApiKeyScope.ADMIN))],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    if exc.http_status >= 500:
        logger.error(
            "app_exception",
            extra={"path": request.url.path, "error_code": exc.error_code, "detail": exc.message},
        )

    client_message = (
        "El sistema no pudo completar la operacion porque uno de los servicios de los que depende "
        "no esta disponible en este momento. Volve a intentarlo en unos minutos."
        if isinstance(exc, InfrastructureError)
        else exc.message
    )
    response = JSONResponse(
        status_code=exc.http_status,
        content={"error_code": exc.error_code, "message": client_message, "details": exc.details},
    )
    if isinstance(exc, RateLimitExceededError):
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
    if isinstance(exc, AuthenticationError):
        response.headers["WWW-Authenticate"] = "ApiKey"
    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "validation_error",
            "message": "Los datos enviados no son validos",
            "details": {"errors": jsonable_encoder(exc.errors())},
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Único lugar del sistema que atrapa Exception genérica: borde HTTP final (noqa: BLE001)
    logger.exception("unhandled_exception", extra={"path": request.url.path, "error": str(exc)})  # noqa: BLE001
    return JSONResponse(
        status_code=500,
        content={"error_code": "internal_error", "message": "Ocurrio un error interno inesperado"},
    )


app.include_router(api_router, prefix="/api/v1")

# asgi_app envuelve con ProxyHeadersMiddleware para resolver la IP real del cliente de forma segura
asgi_app = ProxyHeadersMiddleware(app, trusted_hosts=get_settings().TRUSTED_PROXY_IPS.split(","))
