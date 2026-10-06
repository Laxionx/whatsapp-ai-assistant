"""Fixtures compartidas: configuración aislada y cliente HTTP simulado."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import http
from app.config import Settings
from app.main import create_app
from app.security import compute_signature

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify"
ADMIN_TOKEN = "test-admin"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        whatsapp_verify_token=VERIFY_TOKEN,
        whatsapp_app_secret=APP_SECRET,
        admin_token=ADMIN_TOKEN,
        negocio_path=ROOT / "config" / "negocio.yaml",
        db_path=tmp_path / "test.db",
    )


def with_settings(base: Settings, **changes: object) -> Settings:
    """Copia validada (convierte str a SecretStr, a diferencia de model_copy)."""
    return Settings(_env_file=None, **{**dict(base), **changes})


@pytest.fixture
def sent_calls(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Sustituye el cliente HTTP: registra las peticiones y responde 200 sin red."""
    return install_http_mock(monkeypatch, lambda req: httpx.Response(200, json={"ok": True}))


def install_http_mock(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    def fake_client(timeout: float = 10.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))

    monkeypatch.setattr(http, "make_client", fake_client)
    return calls


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


def text_payload(text: str, message_id: str = "wamid.1", wa_id: str = "51900000001") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": wa_id, "profile": {"name": "Ana"}}],
                            "messages": [
                                {
                                    "id": message_id,
                                    "from": wa_id,
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }


def post_signed(client: TestClient, payload: dict, secret: str = APP_SECRET):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhook",
        content=body,
        headers={"X-Hub-Signature-256": compute_signature(secret, body)},
    )
