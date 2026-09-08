from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    ENVIRONMENT: Literal["local", "docker", "production"] = "local"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = ["*"]
    DOCS_ENABLED: bool | None = None

    # --- OpenAI ---
    OPENAI_API_KEY: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("OPENAI_API_KEY", "OPENAI_APIKEY")
    )
    OPENAI_CHAT_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    LLM_TEMPERATURE: float = 0.0

    # --- Pinecone ---
    PINECONE_API_KEY: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("PINECONE_API_KEY", "PINECONE_APIKEY")
    )
    PINECONE_INDEX_NAME: str = "intelligence-system"
    PINECONE_DIMENSION: int = 1536
    PINECONE_METRIC: str = "cosine"
    PINECONE_CLOUD: str = "aws"
    PINECONE_REGION: str = "us-east-1"
    PINECONE_UPSERT_BATCH_SIZE: int = 100

    # --- Postgres (tablas propias: SQLAlchemy async + asyncpg) ---
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "intelligence_system"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr = SecretStr("postgres")
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10

    # --- Checkpointer LangGraph (psycopg, pool separado) ---
    CHECKPOINTER_POOL_MIN_SIZE: int = 1
    CHECKPOINTER_POOL_MAX_SIZE: int = 10

    # --- Redis ---
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_INGEST_QUEUE_KEY: str = "ingestion:jobs"

    # --- Ingesta ---
    MAX_UPLOAD_SIZE_MB: int = 20
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 150
    UPLOAD_DIR: str = "data/uploads"
    INGESTION_JOB_TIMEOUT_MINUTES: int = 15
    INGESTION_MAX_RETRIES: int = 3
    INGESTION_CONTENT_SCAN_ENABLED: bool = True

    # --- Agentes / grafo ---
    MAX_SUPERVISOR_ITERATIONS: int = 6
    GRAPH_RECURSION_LIMIT: int = 25
    STRUCTURED_OUTPUT_MAX_ATTEMPTS: int = 3
    ESCALATION_HISTORY_WINDOW: int = 10

    # --- Cliente academico (mock hasta que se conecte la API real) ---
    ACADEMIC_API_BASE_URL: str | None = None
    ACADEMIC_API_TIMEOUT_SECONDS: float = 10.0

    # --- Notificaciones HOTL ---
    HOTL_NOTIFICATION_ENABLED: bool = True
    HOTL_WEBHOOK_URL: str | None = None
    HOTL_NOTIFICATION_TIMEOUT_SECONDS: float = 5.0

    # --- Observabilidad & Métricas ---
    PHOENIX_COLLECTOR_ENDPOINT: str = "http://localhost:6006/v1/traces"
    PHOENIX_PROJECT_NAME: str = "intelligence-system"
    PHOENIX_ENABLED: bool = True
    PROMETHEUS_METRICS_ENABLED: bool = True

    # --- Seguridad / auth ---
    API_KEY_HEADER_NAME: str = "X-API-Key"
    API_KEY_PEPPER: SecretStr = SecretStr("")
    BOOTSTRAP_ADMIN_API_KEY: SecretStr | None = None

    # --- Rate limiting ---
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_ANONYMOUS_PER_MINUTE: int = 20
    RATE_LIMIT_CLIENT_PER_MINUTE: int = 60
    RATE_LIMIT_CLIENT_CHAT_PER_MINUTE: int = 15
    RATE_LIMIT_ADMIN_PER_MINUTE: int = 120

    # --- Proxy / IP ---
    TRUSTED_PROXY_IPS: str = "127.0.0.1"
    ADMIN_IP_ALLOWLIST: str = ""

    # --- Retrieval hibrido (FTS Postgres + vectorial Pinecone) ---
    HYBRID_RETRIEVAL_ENABLED: bool = True
    LEXICAL_WEIGHT: float = 0.4
    VECTOR_WEIGHT: float = 0.6
    HYBRID_CANDIDATE_MULTIPLIER: int = 3

    # --- Evaluacion RAG (LLM-as-judge) ---
    EVALUATION_PASS_THRESHOLD: float = 0.7

    @property
    def database_url(self) -> str:
        """DSN async para SQLAlchemy/asyncpg. No es un computed_field a proposito:
        una property comun nunca se serializa en model_dump(), asi la password
        no puede terminar filtrada en un log o una respuesta accidental."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD.get_secret_value()}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def postgres_dsn(self) -> str:
        """DSN libpq plano (sin '+asyncpg') para el pool psycopg del checkpointer."""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD.get_secret_value()}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
