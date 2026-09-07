"""Interfaces que desacoplan agentes/servicios de una implementacion concreta.

AcademicClientProtocol es el punto de extension clave: hoy lo implementa
MockAcademicClient (datos simulados), y el dia que haya una API universitaria
real alcanza con escribir una clase nueva que cumpla el mismo contrato -- nada
en agents/tools/schemas cambia.
"""

from typing import Protocol

from app.schemas.academic import AulaInfo, CodigoMatriculacionInfo, HorarioInfo


class AcademicClientProtocol(Protocol):
    async def get_horarios(
        self, carrera: str, materia: str | None = None, cuatrimestre: str | None = None
    ) -> list[HorarioInfo]: ...

    async def get_codigo_matriculacion(self, materia: str, carrera: str) -> CodigoMatriculacionInfo: ...

    async def get_aula(self, materia: str, comision: str | None = None) -> AulaInfo: ...
