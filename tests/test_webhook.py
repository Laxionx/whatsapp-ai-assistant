"""Verificación del webhook, firma, idempotencia y envío a la Graph API."""

import json

import httpx
from conftest import ADMIN_TOKEN, APP_SECRET, VERIFY_TOKEN, post_signed, text_payload, with_settings
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def test_verification_returns_challenge(client: TestClient) -> None:
    params = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "12345"}
    resp = client.get("/webhook", params=params)
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_verification_rejects_wrong_token_or_mode(client: TestClient) -> None:
    bad_token = {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"}
    bad_mode = {"hub.mode": "other", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "1"}
    assert client.get("/webhook", params=bad_token).status_code == 403
    assert client.get("/webhook", params=bad_mode).status_code == 403
    assert client.get("/webhook").status_code == 403


def test_empty_verify_token_never_matches(settings: Settings) -> None:
    open_client = TestClient(create_app(with_settings(settings, whatsapp_verify_token="")))
    params = {"hub.mode": "subscribe", "hub.challenge": "1"}
    assert open_client.get("/webhook", params=params).status_code == 403


def test_invalid_signature_is_rejected(client: TestClient, sent_calls: list) -> None:
    resp = post_signed(client, text_payload("hola"), secret="otro-secreto")
    assert resp.status_code == 403
    assert client.get("/admin/conversations", headers=AUTH).json() == []


def test_missing_signature_is_rejected(client: TestClient) -> None:
    body = json.dumps(text_payload("hola")).encode()
    assert client.post("/webhook", content=body).status_code == 403


def test_tampered_body_is_rejected(client: TestClient) -> None:
    from app.security import compute_signature

    good = json.dumps(text_payload("hola")).encode()
    tampered = json.dumps(text_payload("hola!")).encode()
    resp = client.post(
        "/webhook",
        content=tampered,
        headers={"X-Hub-Signature-256": compute_signature(APP_SECRET, good)},
    )
    assert resp.status_code == 403


def test_invalid_json_with_valid_signature(client: TestClient) -> None:
    from app.security import compute_signature

    for body in (b"no es json", b"[1, 2]"):
        resp = client.post(
            "/webhook",
            content=body,
            headers={"X-Hub-Signature-256": compute_signature(APP_SECRET, body)},
        )
        assert resp.status_code == 400


def test_valid_message_is_answered_with_faq(client: TestClient, sent_calls: list) -> None:
    resp = post_signed(client, text_payload("¿A qué hora abren?"))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "messages": 1}
    detail = client.get("/admin/conversations/51900000001", headers=AUTH).json()
    assert [m["direction"] for m in detail] == ["in", "out"]
    assert "6:00" in detail[1]["body"]


def test_duplicate_message_is_processed_once(client: TestClient, sent_calls: list) -> None:
    payload = text_payload("hola", message_id="wamid.dup")
    post_signed(client, payload)
    post_signed(client, payload)
    detail = client.get("/admin/conversations/51900000001", headers=AUTH).json()
    assert len(detail) == 2  # un entrante y una respuesta, no cuatro


def test_status_events_are_ignored(client: TestClient, sent_calls: list) -> None:
    status = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "read"}]}}]}]}
    resp = post_signed(client, status)
    assert resp.json()["messages"] == 0
    assert client.get("/admin/conversations", headers=AUTH).json() == []


def test_malformed_entries_are_skipped(client: TestClient) -> None:
    payload = {"entry": [{"changes": [{"value": {"messages": [{"type": "text"}]}}]}]}
    assert post_signed(client, payload).json()["messages"] == 0


def test_non_text_message_gets_polite_reply(client: TestClient, sent_calls: list) -> None:
    payload = text_payload("x")
    msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
    msg.update({"type": "image", "id": "wamid.img"})
    msg.pop("text")
    post_signed(client, payload)
    detail = client.get("/admin/conversations/51900000001", headers=AUTH).json()
    assert "solo entiendo mensajes de texto" in detail[1]["body"]


def test_handoff_keyword_silences_bot(client: TestClient, sent_calls: list) -> None:
    post_signed(client, text_payload("quiero hablar con un humano", "wamid.h1"))
    post_signed(client, text_payload("¿hay alguien?", "wamid.h2"))
    detail = client.get("/admin/conversations/51900000001", headers=AUTH).json()
    assert [m["direction"] for m in detail] == ["in", "out", "in"]
    assert detail[1]["source"] == "handoff"
    listing = client.get("/admin/conversations", headers=AUTH).json()
    assert listing[0]["handoff"] is True


def test_reply_is_sent_to_graph_api(settings: Settings, monkeypatch, sent_calls: list) -> None:
    live = with_settings(
        settings,
        whatsapp_access_token="tok-123",
        whatsapp_phone_number_id="555",
        graph_api_version="v99.0",
    )
    live_client = TestClient(create_app(live))
    post_signed(live_client, text_payload("hola"))
    assert len(sent_calls) == 1
    req = sent_calls[0]
    assert str(req.url) == "https://graph.facebook.com/v99.0/555/messages"
    assert req.headers["Authorization"] == "Bearer tok-123"
    body = json.loads(req.content)
    assert body["to"] == "51900000001" and body["messaging_product"] == "whatsapp"
    assert "Bienvenido" in body["text"]["body"]


def test_graph_api_failure_does_not_break_webhook(settings: Settings, monkeypatch, caplog) -> None:
    from conftest import install_http_mock

    install_http_mock(monkeypatch, lambda req: httpx.Response(401, json={"error": "bad token"}))
    live = with_settings(
        settings, whatsapp_access_token="tok-secret-xyz", whatsapp_phone_number_id="555"
    )
    live_client = TestClient(create_app(live))
    with caplog.at_level("INFO"):
        resp = post_signed(live_client, text_payload("hola"))
    assert resp.status_code == 200
    assert "Fallo al enviar" in caplog.text
    assert "tok-secret-xyz" not in caplog.text
    assert "51900000001" not in caplog.text  # el número va enmascarado


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
