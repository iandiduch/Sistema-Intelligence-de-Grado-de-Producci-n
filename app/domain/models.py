"""Enums de dominio. Sin logica, sin dependencias de infraestructura -- solo
vocabulario compartido entre schemas, servicios, agentes y persistencia."""

from enum import Enum


class AgentRole(str, Enum):
    SUPERVISOR = "supervisor"
    KNOWLEDGE = "knowledge_agent"
    ACADEMIC = "academic_agent"
    VALIDATOR = "validator"
    ESCALATION = "escalation_agent"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class FileType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"


class EscalationStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ContactChannel(str, Enum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"


class EscalationType(str, Enum):
    NO_INFO_FOUND = "NO_INFO_FOUND"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    REQUIRES_HUMAN_ACTION = "REQUIRES_HUMAN_ACTION"
    MAX_LOOPS_EXCEEDED = "MAX_LOOPS_EXCEEDED"
    USER_REQUESTED = "USER_REQUESTED"


class EscalationPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_FOUND = "not_found"


class ApiKeyScope(str, Enum):
    """Admin incluye todo lo que puede hacer client -- ver la jerarquia en
    app/core/security.py::require_scope."""

    CLIENT = "client"
    ADMIN = "admin"
