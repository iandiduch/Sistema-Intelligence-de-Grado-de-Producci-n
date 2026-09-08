"""Schemas de salida estructurada de cada nodo del grafo. Viven separados de
agents.py para que servicios/tests puedan importarlos sin arrastrar LangGraph."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import ConfidenceLevel, ContactChannel, EscalationType


class SupervisorDecision(BaseModel):
    next_agent: Literal["knowledge_agent", "academic_agent", "validator", "escalation_agent", "__end__"]
    reasoning: str = Field(..., description="Motivo breve de la decision de ruteo")
    direct_reply: str | None = Field(
        default=None,
        description="Solo si next_agent es __end__: respuesta breve para saludos o cierre de charla, sin logica de negocio",
    )


class Referencia(BaseModel):
    fuente: str = Field(..., description="Nombre del archivo fuente")
    chunk_id: str
    fragmento: str = Field(..., description="Fragmento textual citado")
    page: int | None = None


class KnowledgeAgentOutput(BaseModel):
    encontrado_en_contexto: bool
    nivel_de_confianza: ConfidenceLevel
    respuesta: str
    referencias: list[Referencia] = Field(default_factory=list)


class AcademicAgentOutput(BaseModel):
    respuesta: str
    datos: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ValidatorOutput(BaseModel):
    es_suficiente: bool
    requiere_mas_info: bool
    confianza: ConfidenceLevel
    razon: str
    respuesta_sintetizada: str | None = None
    escalation_type: EscalationType | None = None


class ContactIntent(str, Enum):
    PROVIDE_CONTACT = "provide_contact"
    DECLINE = "decline"
    UNCLEAR = "unclear"


class ContactCapture(BaseModel):
    is_complete: bool = Field(
        default=False,
        description="True únicamente si el estudiante proporcionó un email o teléfono válido",
    )
    intent: ContactIntent = Field(
        default=ContactIntent.UNCLEAR,
        description=(
            "Intención del estudiante en lenguaje natural: "
            "'provide_contact' si proporciona un email o teléfono; "
            "'decline' si rechaza, declina o cancela la derivación (ej. 'no', 'no quiero', 'cancelar', 'dejalo', 'no gracias', 'paso'); "
            "'unclear' si el mensaje es ambiguo o una duda no relacionada."
        ),
    )
    contact_channel: ContactChannel | None = None
    contact_value: str | None = None
