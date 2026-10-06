"""Envía al servidor local un webhook falso firmado, sin necesidad de cuenta de Meta.

Uso: python scripts/simular_mensaje.py "¿A qué hora abren?" [--url http://127.0.0.1:8000]
Lee WHATSAPP_APP_SECRET y ADMIN_TOKEN del .env (los mismos que usa el servidor).
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.security import compute_signature  # noqa: E402

POLL_SECONDS = 5.0


def build_payload(text: str, wa_id: str, message_id: str) -> dict:
    """Estructura mínima idéntica a la que envía la Cloud API."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "FAKE_WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "FAKE_PHONE_ID"},
                            "contacts": [
                                {"wa_id": wa_id, "profile": {"name": "Cliente de prueba"}}
                            ],
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": wa_id,
                                    "type": "text",
                                    "timestamp": str(int(time.time())),
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def wait_for_reply(client: httpx.Client, url: str, token: str, wa_id: str) -> str | None:
    """Consulta el endpoint de administración hasta ver la respuesta del bot."""
    deadline = time.time() + POLL_SECONDS
    while time.time() < deadline:
        resp = client.get(
            f"{url}/admin/conversations/{wa_id}", headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code == 200:
            outgoing = [m for m in resp.json() if m["direction"] == "out"]
            if outgoing:
                return outgoing[-1]["body"]
        time.sleep(0.2)
    return None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # consolas de Windows
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("texto", help="Mensaje que 'escribe' el cliente")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--numero", default="51999000111", help="Número ficticio del cliente")
    args = parser.parse_args()

    settings = Settings()
    secret = settings.whatsapp_app_secret.get_secret_value()
    if not secret:
        print("Falta WHATSAPP_APP_SECRET en el .env", file=sys.stderr)
        return 2

    body = json.dumps(
        build_payload(args.texto, args.numero, f"wamid.SIM{uuid.uuid4().hex}")
    ).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": compute_signature(secret, body),
    }
    with httpx.Client(timeout=10) as client:
        resp = client.post(f"{args.url}/webhook", content=body, headers=headers)
        print(f"Webhook -> HTTP {resp.status_code} {resp.text}")
        if resp.status_code != 200:
            return 1
        token = settings.admin_token.get_secret_value()
        if not token:
            print("Sin ADMIN_TOKEN no puedo mostrar la respuesta del bot.")
            return 0
        reply = wait_for_reply(client, args.url, token, args.numero)
    print(f"Cliente: {args.texto}")
    print(f"Bot:     {reply or '(sin respuesta)'}")
    return 0 if reply else 1


if __name__ == "__main__":
    sys.exit(main())
