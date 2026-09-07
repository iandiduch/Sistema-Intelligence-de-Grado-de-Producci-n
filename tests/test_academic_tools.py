"""MockAcademicClient + validacion y ejecucion de las tools academicas."""

import pytest
from pydantic import ValidationError

from app.agents.tools.academic_tools import (
    ConsultarAulaInput,
    ConsultarCodigoMatriculacionInput,
    ConsultarHorariosInput,
    build_academic_tools,
)
from app.core.exceptions import AcademicAPIError
from app.services.academic_client import MockAcademicClient


async def test_get_horarios_is_deterministic():
    client = MockAcademicClient()
    first = await client.get_horarios("Ingenieria en Sistemas", "Algoritmos I")
    second = await client.get_horarios("Ingenieria en Sistemas", "Algoritmos I")
    assert first == second


async def test_get_horarios_requires_carrera():
    client = MockAcademicClient()
    with pytest.raises(AcademicAPIError):
        await client.get_horarios("")


async def test_get_codigo_matriculacion_shape():
    client = MockAcademicClient()
    info = await client.get_codigo_matriculacion("Algoritmos I", "Ingenieria en Sistemas")
    assert info.codigo.startswith("MAT-")
    assert 0 <= info.cupos_disponibles <= 40


async def test_get_aula_shape():
    client = MockAcademicClient()
    info = await client.get_aula("Algoritmos I")
    assert info.aula.startswith("Aula ")


def test_tools_args_schema_validation():
    with pytest.raises(ValidationError):
        ConsultarHorariosInput()  # carrera es obligatoria

    ConsultarCodigoMatriculacionInput(materia="Algoritmos I", carrera="Sistemas")
    ConsultarAulaInput(materia="Algoritmos I")


def test_build_academic_tools_returns_exactly_three():
    tools = build_academic_tools(MockAcademicClient())
    names = {t.name for t in tools}
    assert names == {"consultar_horarios", "consultar_codigo_matriculacion", "consultar_aula"}


async def test_consultar_horarios_tool_invocation():
    tools = build_academic_tools(MockAcademicClient())
    tool = next(t for t in tools if t.name == "consultar_horarios")
    result = await tool.ainvoke({"carrera": "Ingenieria en Sistemas"})
    assert isinstance(result, list)
    assert len(result) == 3  # sin materia puntual, el mock devuelve 3 materias
