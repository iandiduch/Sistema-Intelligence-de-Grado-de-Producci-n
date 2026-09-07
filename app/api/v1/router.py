"""Agrupador central de rutas v1. El prefijo /api/v1 se aplica una unica vez
en app/main.py, no aca.

Proteccion por scope aplicada por router. `require_scope(CLIENT)` en /chat usa
ademas el limite estricto de RATE_LIMIT_CLIENT_CHAT_PER_MINUTE -- es el
endpoint que dispara llamadas reales a OpenAI, el costo real esta ahi.

`/ingest` requiere scope ADMIN (no CLIENT como el resto de las operaciones
de uso corriente): quien puede escribir en la base documental que despues
alimenta a knowledge_agent para TODOS los usuarios tiene que ser un conjunto
de confianza mas chico que quien simplemente puede chatear -- si compartieran
scope, cualquier key client podria envenenar el RAG (prompt injection
indirecta) para el resto de la poblacion de usuarios."""

from fastapi import APIRouter, Depends

from app.api.v1.endpoints import (
    api_keys,
    chat,
    escalations,
    health,
    ingest,
    prompts,
)
from app.core.security import rate_limited, require_scope
from app.domain.models import ApiKeyScope

api_router = APIRouter()

_client = Depends(require_scope(ApiKeyScope.CLIENT))
_client_rate_limited = Depends(rate_limited())
_admin = Depends(require_scope(ApiKeyScope.ADMIN))
_admin_rate_limited = Depends(rate_limited())

api_router.include_router(
    chat.router,
    tags=["chat"],
    dependencies=[_client, Depends(rate_limited(strict_chat_limit=True))],
)
api_router.include_router(ingest.router, tags=["ingest"], dependencies=[_admin, _admin_rate_limited])
api_router.include_router(escalations.router, tags=["escalations"], dependencies=[_client, _client_rate_limited])
api_router.include_router(prompts.router, tags=["prompts"], dependencies=[_admin, _admin_rate_limited])
api_router.include_router(api_keys.router, tags=["admin"], dependencies=[_admin, _admin_rate_limited])
api_router.include_router(health.router, tags=["health"])  # sin proteccion: lo pegan health checks de infra
