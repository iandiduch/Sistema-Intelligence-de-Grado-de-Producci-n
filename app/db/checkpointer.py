"""Pool psycopg dedicado exclusivamente al checkpointer de LangGraph. Nunca se
comparte con el engine SQLAlchemy/asyncpg de app/db/session.py: son dos dueños
distintos (LangGraph gestiona su propio schema internamente, nosotros el nuestro).

`.setup()` corre una unica vez desde scripts/init_db.py -- ver ese archivo.
"""

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import Settings

_CONNECTION_KWARGS = {"autocommit": True, "row_factory": dict_row}


async def build_checkpointer_pool(settings: Settings, timeout: float = 5.0) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        conninfo=settings.postgres_dsn,
        max_size=settings.CHECKPOINTER_POOL_MAX_SIZE,
        min_size=settings.CHECKPOINTER_POOL_MIN_SIZE,
        timeout=timeout,
        kwargs=_CONNECTION_KWARGS,
        open=False,
    )
    await pool.open(wait=False)
    return pool


def build_checkpointer(pool: AsyncConnectionPool) -> AsyncPostgresSaver:
    return AsyncPostgresSaver(pool)
