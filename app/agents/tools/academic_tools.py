"""Tools academicas: envuelven AcademicClientProtocol (mock hoy, API real
despues) con un args_schema Pydantic explicito por herramienta."""

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.domain.protocols import AcademicClientProtocol


class ConsultarHorariosInput(BaseModel):
    carrera: str = Field(..., description="Carrera a consultar")
    materia: str | None = Field(default=None, description="Materia puntual, si se conoce")
    cuatrimestre: str | None = Field(default=None, description="Cuatrimestre, ej. '1er cuatrimestre 2026'")


class ConsultarCodigoMatriculacionInput(BaseModel):
    materia: str = Field(..., description="Materia a matricular")
    carrera: str = Field(..., description="Carrera de la materia")


class ConsultarAulaInput(BaseModel):
    materia: str = Field(..., description="Materia a consultar")
    comision: str | None = Field(default=None, description="Comision puntual, si se conoce")


def build_academic_tools(client: AcademicClientProtocol) -> list[BaseTool]:
    @tool("consultar_horarios", args_schema=ConsultarHorariosInput)
    async def consultar_horarios(
        carrera: str, materia: str | None = None, cuatrimestre: str | None = None
    ) -> list[dict]:
        """Consulta horarios de cursada para una carrera (y opcionalmente una materia/cuatrimestre puntual)."""
        horarios = await client.get_horarios(carrera, materia, cuatrimestre)
        return [h.model_dump(mode="json") for h in horarios]

    @tool("consultar_codigo_matriculacion", args_schema=ConsultarCodigoMatriculacionInput)
    async def consultar_codigo_matriculacion(materia: str, carrera: str) -> dict:
        """Consulta el codigo de matriculacion y los cupos disponibles de una materia."""
        info = await client.get_codigo_matriculacion(materia, carrera)
        return info.model_dump(mode="json")

    @tool("consultar_aula", args_schema=ConsultarAulaInput)
    async def consultar_aula(materia: str, comision: str | None = None) -> dict:
        """Consulta el aula y edificio asignados a una materia/comision."""
        info = await client.get_aula(materia, comision)
        return info.model_dump(mode="json")

    return [consultar_horarios, consultar_codigo_matriculacion, consultar_aula]
