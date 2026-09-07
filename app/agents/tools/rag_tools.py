"""Tool de búsqueda que usa el Knowledge Agent.

Se construye vía factory para inyectar el índice de Pinecone, el sessionmaker de
Postgres (para FTS léxico) y el cliente de embeddings sin recurrir a singletons globales.
"""

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.services.rag_service import hybrid_search


class BuscarConocimientoInput(BaseModel):
    query: str = Field(..., description="Pregunta o tema a buscar en la base de conocimiento institucional")
    top_k: int = Field(default=5, ge=1, le=20)


def build_rag_tools(
    index,
    embeddings_client,
    sessionmaker: async_sessionmaker[AsyncSession] | None,
    settings: Settings,
) -> list[BaseTool]:
    @tool("buscar_conocimiento_institucional", args_schema=BuscarConocimientoInput)
    async def buscar_conocimiento_institucional(query: str, top_k: int = 5) -> list[dict]:
        """Busca en la base de conocimiento institucional (reglamentos, planes
        de estudio, procedimientos) y devuelve los fragmentos más relevantes
        junto con su fuente."""
        chunks = await hybrid_search(query, top_k, index, embeddings_client, sessionmaker, settings)
        return [chunk.model_dump(mode="json") for chunk in chunks]

    return [buscar_conocimiento_institucional]
