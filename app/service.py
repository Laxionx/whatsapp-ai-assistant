"""Lógica de un mensaje entrante: idempotencia, cerebro, respuesta e historial."""

import logging

from app import whatsapp
from app.brain import generate_reply
from app.config import Settings
from app.db import Store
from app.negocio import Negocio
from app.whatsapp import IncomingMessage

log = logging.getLogger(__name__)


async def handle_message(
    settings: Settings, store: Store, negocio: Negocio, msg: IncomingMessage
) -> None:
    if not store.claim_message(msg.id):
        log.info("Mensaje duplicado ignorado: %s", msg.id)
        return

    # Historial previo al mensaje actual (el LLM recibe el mensaje aparte).
    history = store.history(msg.wa_id)
    body = msg.text if msg.text is not None else "[mensaje no soportado]"
    store.add_message(msg.wa_id, "in", body, name=msg.name)

    if store.is_handoff(msg.wa_id):
        log.info(
            "Conversación %s en manos de un humano; el bot no responde", whatsapp.mask(msg.wa_id)
        )
        return

    if msg.text is None:
        reply_text, source = negocio.mensaje_no_texto, "rules"
    else:
        reply = await generate_reply(settings, negocio, msg.text, history)
        reply_text, source = reply.text, reply.source
        if source == "handoff":
            store.set_handoff(msg.wa_id)

    store.add_message(msg.wa_id, "out", reply_text, source=source)
    await whatsapp.send_text(settings, msg.wa_id, reply_text)
