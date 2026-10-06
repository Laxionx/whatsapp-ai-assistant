"""Cerebro (a): reglas/FAQ por palabras clave desde el YAML."""

import re
import unicodedata

from app.negocio import Negocio


def normalize(text: str) -> str:
    """Minúsculas y sin acentos, para comparar sin sorpresas."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def _score(clave: str, text: str) -> int:
    pattern = rf"\b{re.escape(normalize(clave))}"
    return len(re.findall(pattern, text))


def reply_rules(negocio: Negocio, text: str) -> str:
    """Devuelve la respuesta de la FAQ con más coincidencias, o la por defecto."""
    norm = normalize(text)
    best_score, best_answer = 0, negocio.mensaje_por_defecto
    for entry in negocio.faq:
        score = sum(_score(clave, norm) for clave in entry.claves)
        if score > best_score:
            best_score, best_answer = score, entry.respuesta
    return best_answer
