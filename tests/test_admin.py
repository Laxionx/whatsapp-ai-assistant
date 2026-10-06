"""Endpoint de administración, almacenamiento y entrada principal."""

from pathlib import Path

import pytest
from conftest import ADMIN_TOKEN, post_signed, text_payload, with_settings
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Store
from app.main import app_factory, create_app
from app.negocio import load_negocio

AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def test_admin_requires_valid_token(client: TestClient) -> None:
    assert client.get("/admin/conversations").status_code == 401
    assert (
        client.get("/admin/conversations", headers={"Authorization": "Bearer mal"}).status_code
        == 401
    )
    assert client.get("/admin/conversations", headers=AUTH).status_code == 200


def test_admin_disabled_without_configured_token(settings: Settings) -> None:
    closed = TestClient(create_app(with_settings(settings, admin_token="")))
    assert (
        closed.get("/admin/conversations", headers={"Authorization": "Bearer "}).status_code == 401
    )
    assert closed.get("/admin/conversations").status_code == 401


def test_admin_lists_conversations_with_pagination(client: TestClient, sent_calls: list) -> None:
    for i in range(3):
        post_signed(client, text_payload("hola", f"wamid.{i}", wa_id=f"5190000000{i}"))
    listing = client.get("/admin/conversations", headers=AUTH).json()
    assert len(listing) == 3
    assert listing[0]["wa_id"] == "51900000002"  # la más reciente primero
    assert listing[0]["message_count"] == 2 and listing[0]["name"] == "Ana"
    page = client.get("/admin/conversations?limit=1&offset=1", headers=AUTH).json()
    assert [c["wa_id"] for c in page] == ["51900000001"]
    assert client.get("/admin/conversations?limit=0", headers=AUTH).status_code == 422


def test_admin_unknown_conversation_is_404(client: TestClient) -> None:
    assert client.get("/admin/conversations/000", headers=AUTH).status_code == 404


def test_store_history_in_chat_format(tmp_path: Path) -> None:
    store = Store(tmp_path / "h.db")
    store.add_message("1", "in", "hola")
    store.add_message("1", "out", "buenas", source="rules")
    assert store.history("1") == [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "buenas"},
    ]
    assert store.history("1", limit=1) == [{"role": "assistant", "content": "buenas"}]
    assert store.claim_message("a") is True and store.claim_message("a") is False


def test_store_handoff_flag(tmp_path: Path) -> None:
    store = Store(tmp_path / "h.db")
    assert store.is_handoff("1") is False
    store.add_message("1", "in", "hola")
    store.set_handoff("1")
    assert store.is_handoff("1") is True
    store.set_handoff("1", False)
    assert store.is_handoff("1") is False


def test_real_http_client_factory() -> None:
    from app import http

    assert http.make_client(3.0).timeout.read == 3.0


def test_invalid_yaml_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("nombre: X\nfaq: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_negocio(bad)


def test_app_factory_builds_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parent.parent
    monkeypatch.setenv("NEGOCIO_PATH", str(root / "config" / "negocio.yaml"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "f.db"))
    assert TestClient(app_factory()).get("/health").status_code == 200
