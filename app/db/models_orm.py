"""ORM de las tablas propias (ingestion_jobs, escalation_tickets, agent_prompts,
api_keys, document_chunks).

Nombrado `models_orm.py` (no `models.py`) para no chocar con app/domain/models.py
(los enums de dominio). Las tablas del checkpointer de LangGraph son propiedad de
`AsyncPostgresSaver` y no tienen ORM propio aca -- nunca se consultan directo.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint("file_type IN ('pdf','docx','txt','md')", name="ck_ingestion_jobs_file_type"),
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','COMPLETED','FAILED')", name="ck_ingestion_jobs_status"
        ),
        Index("ix_ingestion_jobs_status", "status"),
        Index("ix_ingestion_jobs_created_at", "created_at"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str]
    file_type: Mapped[str]
    storage_path: Mapped[str]
    status: Mapped[str] = mapped_column(default="PENDING")
    retry_count: Mapped[int] = mapped_column(default=0)
    chunks_indexed: Mapped[int | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(default=None)
    job_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    completed_at: Mapped[datetime | None] = mapped_column(default=None)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class EscalationTicket(Base):
    __tablename__ = "escalation_tickets"
    __table_args__ = (
        CheckConstraint(
            "escalation_type IN ('NO_INFO_FOUND','LOW_CONFIDENCE','REQUIRES_HUMAN_ACTION',"
            "'MAX_LOOPS_EXCEEDED','USER_REQUESTED')",
            name="ck_escalation_tickets_type",
        ),
        CheckConstraint("priority IN ('LOW','MEDIUM','HIGH','URGENT')", name="ck_escalation_tickets_priority"),
        CheckConstraint("contact_channel IN ('EMAIL','WHATSAPP')", name="ck_escalation_tickets_channel"),
        CheckConstraint(
            "status IN ('PENDING','IN_PROGRESS','RESOLVED','CANCELLED')", name="ck_escalation_tickets_status"
        ),
        Index("ix_escalation_tickets_status", "status"),
        Index("ix_escalation_tickets_thread_id", "thread_id"),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[str]
    original_question: Mapped[str]
    relevant_history: Mapped[list] = mapped_column(JSONB, default=list)
    reason: Mapped[str]
    escalation_type: Mapped[str]
    priority: Mapped[str] = mapped_column(default="MEDIUM")
    contact_channel: Mapped[str]
    contact_value: Mapped[str]
    status: Mapped[str] = mapped_column(default="PENDING")
    resolution_notes: Mapped[str | None] = mapped_column(default=None)
    resolved_by: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(default=None)


class AgentPrompt(Base):
    __tablename__ = "agent_prompts"

    agent_id: Mapped[str] = mapped_column(primary_key=True)
    content: Mapped[str]
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[str | None] = mapped_column(default=None)


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("scope IN ('client','admin')", name="ck_api_keys_scope"),
        Index("ix_api_keys_is_active", "is_active"),
    )

    key_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # sha256(pepper + plaintext) -- nunca se guarda la key en texto plano, ni
    # siquiera un prefijo de ella. El lookup es un match exacto sobre esta
    # columna (indexada via UNIQUE), no una comparacion lineal.
    key_hash: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    scope: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(default=None)
    created_by: Mapped[str | None] = mapped_column(default=None)


class DocumentChunk(Base):
    """Copia del texto de cada chunk y metadatos en PostgreSQL para búsqueda léxica FTS."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint("file_type IN ('pdf','docx','txt','md')", name="ck_document_chunks_file_type"),
        Index("ix_document_chunks_fts", text("to_tsvector('spanish', text)"), postgresql_using="gin"),
        Index("ix_document_chunks_document_id", "document_id"),
    )

    chunk_id: Mapped[str] = mapped_column(primary_key=True)
    document_id: Mapped[str]
    filename: Mapped[str]
    file_type: Mapped[str]
    page: Mapped[int | None] = mapped_column(default=None)
    section: Mapped[str | None] = mapped_column(default=None)
    source: Mapped[str]
    text: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
