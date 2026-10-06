"""Carga y validación del YAML del negocio."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class FaqEntry(BaseModel):
    claves: list[str] = Field(min_length=1)
    respuesta: str


class Negocio(BaseModel):
    nombre: str
    descripcion: str = ""
    palabra_humano: str = "humano"
    mensaje_derivacion: str = "Te paso con una persona del equipo."
    mensaje_por_defecto: str = "No te entendí bien. Escribe 'humano' para hablar con alguien."
    mensaje_no_texto: str = "Por ahora solo entiendo mensajes de texto."
    faq: list[FaqEntry] = Field(min_length=1)


def load_negocio(path: Path) -> Negocio:
    with path.open(encoding="utf-8") as fh:
        return Negocio.model_validate(yaml.safe_load(fh))
