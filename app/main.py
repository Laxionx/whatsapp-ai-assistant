"""Aplicación FastAPI: webhook de WhatsApp Cloud API y administración."""

import json
import logging
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import Settings
from app.db import Store
from app.negocio import Negocio, load_negocio
from app.security import tokens_match, verify_signature
from app.service import handle_message
from app.whatsapp import parse_messages

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    negocio: Negocio = load_negocio(settings.negocio_path)
    store = Store(settings.db_path)

    app = FastAPI(title="WhatsApp AI Assistant", version="1.0.0")
    app.state.settings = settings
    app.state.store = store

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/webhook", response_class=PlainTextResponse)
    async def verify(
        mode: Annotated[str | None, Query(alias="hub.mode")] = None,
        token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
        challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
    ) -> str:
        """Verificación inicial de Meta: devuelve el challenge si el token coincide."""
        expected = settings.whatsapp_verify_token.get_secret_value()
        if mode == "subscribe" and challenge is not None and tokens_match(expected, token or ""):
            return challenge
        raise HTTPException(status_code=403, detail="Verificación fallida")

    @app.post("/webhook")
    async def receive(
        request: Request,
        background: BackgroundTasks,
        signature: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
    ) -> dict[str, Any]:
        raw = await request.body()
        if not verify_signature(settings.whatsapp_app_secret.get_secret_value(), raw, signature):
            raise HTTPException(status_code=403, detail="Firma inválida")
        try:
            payload = json.loads(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="JSON inválido") from None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Payload inesperado")

        messages = parse_messages(payload)
        for msg in messages:
            # Se responde en segundo plano: Meta exige un 200 rápido.
            background.add_task(handle_message, settings, store, negocio, msg)
        return {"status": "ok", "messages": len(messages)}

    def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not tokens_match(settings.admin_token.get_secret_value(), given):
            raise HTTPException(status_code=401, detail="No autorizado")

    @app.get("/admin/conversations", dependencies=[Depends(require_admin)])
    async def list_conversations(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict[str, Any]]:
        return store.list_conversations(limit, offset)

    @app.get("/admin/conversations/{wa_id}", dependencies=[Depends(require_admin)])
    async def conversation_detail(wa_id: str) -> list[dict[str, Any]]:
        messages = store.conversation_messages(wa_id)
        if not messages:
            raise HTTPException(status_code=404, detail="Conversación no encontrada")
        return messages

    return app


def app_factory() -> FastAPI:
    """Entrada para uvicorn: `uvicorn app.main:app_factory --factory`."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    return create_app()
