from pydantic import BaseModel, Field


class HorarioInfo(BaseModel):
    materia: str
    carrera: str
    comision: str
    dia: str
    hora_inicio: str
    hora_fin: str
    docente: str
    cuatrimestre: str


class HorariosQuery(BaseModel):
    carrera: str = Field(..., min_length=2, max_length=200)
    materia: str | None = Field(default=None, max_length=200)
    cuatrimestre: str | None = Field(default=None, max_length=20)


class CodigoMatriculacionInfo(BaseModel):
    materia: str
    carrera: str
    codigo: str
    cupos_disponibles: int
    periodo: str


class MatriculacionQuery(BaseModel):
    materia: str = Field(..., min_length=2, max_length=200)
    carrera: str = Field(..., min_length=2, max_length=200)


class AulaInfo(BaseModel):
    materia: str
    comision: str
    aula: str
    edificio: str
    capacidad: int


class AulaQuery(BaseModel):
    materia: str = Field(..., min_length=2, max_length=200)
    comision: str | None = Field(default=None, max_length=50)
