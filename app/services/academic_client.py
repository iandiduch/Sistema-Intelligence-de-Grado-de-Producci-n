"""Cliente academico simulado: cumple AcademicClientProtocol con datos
plausibles y deterministicos (mismo query -> misma respuesta) para que el
Academic Agent funcione de punta a punta. El dia que haya una API real,
alcanza con escribir una clase nueva con el mismo contrato y cambiar el
binding en app/api/dependencies.py -- nada mas se toca."""

import random

from app.core.exceptions import AcademicAPIError
from app.schemas.academic import AulaInfo, CodigoMatriculacionInfo, HorarioInfo

_DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]
_EDIFICIOS = ["Edificio Central", "Anexo Norte", "Anexo Sur"]


class MockAcademicClient:
    async def get_horarios(
        self, carrera: str, materia: str | None = None, cuatrimestre: str | None = None
    ) -> list[HorarioInfo]:
        if not carrera.strip():
            raise AcademicAPIError("La carrera es obligatoria para consultar horarios")

        materias = [materia] if materia else [f"Materia {n}" for n in range(1, 4)]
        rng = random.Random(f"{carrera}:{materia}:{cuatrimestre}")
        return [
            HorarioInfo(
                materia=m,
                carrera=carrera,
                comision=f"C{rng.randint(1, 5)}",
                dia=rng.choice(_DIAS),
                hora_inicio=f"{rng.randint(8, 18):02d}:00",
                hora_fin=f"{rng.randint(19, 22):02d}:00",
                docente=f"Prof. {m.split()[-1]}",
                cuatrimestre=cuatrimestre or "1er cuatrimestre 2026",
            )
            for m in materias
        ]

    async def get_codigo_matriculacion(self, materia: str, carrera: str) -> CodigoMatriculacionInfo:
        if not materia.strip() or not carrera.strip():
            raise AcademicAPIError("Materia y carrera son obligatorias para consultar el codigo de matriculacion")

        rng = random.Random(f"{materia}:{carrera}")
        return CodigoMatriculacionInfo(
            materia=materia,
            carrera=carrera,
            codigo=f"MAT-{rng.randint(1000, 9999)}",
            cupos_disponibles=rng.randint(0, 40),
            periodo="1er cuatrimestre 2026",
        )

    async def get_aula(self, materia: str, comision: str | None = None) -> AulaInfo:
        if not materia.strip():
            raise AcademicAPIError("La materia es obligatoria para consultar el aula")

        rng = random.Random(f"{materia}:{comision}")
        return AulaInfo(
            materia=materia,
            comision=comision or f"C{rng.randint(1, 5)}",
            aula=f"Aula {rng.randint(101, 320)}",
            edificio=rng.choice(_EDIFICIOS),
            capacidad=rng.choice([30, 40, 60, 90]),
        )
