"""Parseo del payload del webhook y envío con la Graph API."""

import logging
from dataclasses import dataclass
from typing import Any

from app import http
from app.config import Settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncomingMessage:
    id: str
    wa_id: str
    name: str | None
    text: str | None  # None si el mensaje no es de texto


def parse_messages(payload: dict[str, Any]) -> list[IncomingMessage]:
    """Extrae los mensajes entrantes; los eventos de estado no traen 'messages'."""
    found: list[IncomingMessage] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            names = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in value.get("contacts") or []
            }
            for msg in value.get("messages") or []:
                if not msg.get("id") or not msg.get("from"):
                    continue
                text = (msg.get("text") or {}).get("body") if msg.get("type") == "text" else None
                found.append(IncomingMessage(msg["id"], msg["from"], names.get(msg["from"]), text))
    return found


def mask(wa_id: str) -> str:
    """Oculta el número en logs: solo los 4 últimos dígitos."""
    return f"***{wa_id[-4:]}"


async def send_text(settings: Settings, to: str, body: str) -> bool:
    """Envía un texto por la Graph API. Devuelve False (sin lanzar) si falla."""
    if not settings.can_send:
        log.info("Modo local: no se envía a Meta (a %s)", mask(to))
        return False
    url = (
        f"{settings.graph_api_base}/{settings.graph_api_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token.get_secret_value()}"}
    try:
        async with http.make_client() as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
    except Exception as exc:
        # Nunca se registra la cabecera ni el cuerpo con credenciales.
        log.error("Fallo al enviar a %s: %s", mask(to), type(exc).__name__)
        return False
    return True
