"""Cerebro intercambiable: reglas, LLM con respaldo y derivación a humano."""

import logging
from dataclasses import dataclass

from app.brain.llm import LLMError, reply_llm
from app.brain.rules import normalize, reply_rules
from app.config import Settings
from app.negocio import Negocio

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Reply:
    text: str
    source: str  # "rules" | "llm" | "handoff"


def wants_human(negocio: Negocio, text: str) -> bool:
    return normalize(negocio.palabra_humano) in normalize(text)


async def generate_reply(
    settings: Settings, negocio: Negocio, text: str, history: list[dict[str, str]]
) -> Reply:
    if wants_human(negocio, text):
        return Reply(negocio.mensaje_derivacion, "handoff")
    if settings.brain == "llm":
        try:
            return Reply(await reply_llm(settings, negocio, text, history), "llm")
        except LLMError as exc:
            log.warning("LLM no disponible (%s); uso reglas", exc)
    return Reply(reply_rules(negocio, text), "rules")
