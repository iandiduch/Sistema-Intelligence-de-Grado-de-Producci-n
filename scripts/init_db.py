"""Setup de infraestructura, se corre UNA sola vez antes de levantar el API y el
worker (nunca en cada arranque de app/main.py):

  1. crea las tablas propias (ingestion_jobs, escalation_tickets, agent_prompts,
     api_keys, document_chunks)
  2. corre AsyncPostgresSaver.setup() -- tablas del checkpointer de LangGraph
  3. crea el indice de Pinecone si todavia no existe
  4. siembra los prompts default si agent_prompts esta vacia
  5. siembra la primera API key admin (BOOTSTRAP_ADMIN_API_KEY) si api_keys esta vacia

Uso: python -m scripts.init_db
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.checkpointer import build_checkpointer, build_checkpointer_pool
from app.db.models_orm import Base
from app.services.api_key_service import seed_bootstrap_admin_key
from app.services.prompt_manager import PromptManager
from app.services.rag_service import build_pinecone_client, ensure_index_exists

logger = logging.getLogger(__name__)

_DEFAULTS_DIR = Path(__file__).resolve().parent.parent / "app" / "agents" / "prompts" / "defaults"


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)

    logger.info("init_db.creating_app_tables")
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    logger.info("init_db.seeding_prompts")
    await PromptManager(sessionmaker).seed_defaults_if_empty(_DEFAULTS_DIR)

    logger.info("init_db.seeding_bootstrap_admin_key")
    await seed_bootstrap_admin_key(sessionmaker, settings)

    await engine.dispose()

    logger.info("init_db.checkpointer_setup")
    pool = await build_checkpointer_pool(settings)
    try:
        await build_checkpointer(pool).setup()
    finally:
        await pool.close()

    logger.info("init_db.ensure_pinecone_index")
    pinecone_client = build_pinecone_client(settings)
    try:
        await ensure_index_exists(pinecone_client, settings)
    finally:
        await pinecone_client.close()

    logger.info("init_db.done")


if __name__ == "__main__":
    asyncio.run(main())
