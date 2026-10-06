"""Reglas FAQ, cerebro LLM con respaldo y carga del YAML."""

import asyncio
import json

import httpx
import pytest
from conftest import ROOT, install_http_mock

from app.brain import generate_reply, wants_human
from app.brain.llm import LLMError, build_system_prompt, reply_llm
from app.brain.rules import normalize, reply_rules
from app.config import Settings
from app.negocio import load_negocio


@pytest.fixture
def negocio():
    return load_negocio(ROOT / "config" / "negocio.yaml")


def test_normalize_strips_accents_and_case() -> None:
    assert normalize("UBICACIÓN Dónde") == "ubicacion donde"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hola, buenas tardes", "Bienvenido"),
        ("¿Cuál es el horario?", "6:00"),
        ("cuanto cuesta el croissant", "S/ 3.50"),
        ("¿Dónde están ubicados? me das la dirección", "Av. Los Olivos"),
        ("quiero hacer un pedido de una torta", "24 horas"),
        ("aceptan yape?", "Yape"),
    ],
)
def test_rules_match_faq(negocio, text: str, expected: str) -> None:
    assert expected in reply_rules(negocio, text)


def test_rules_default_when_no_match(negocio) -> None:
    assert reply_rules(negocio, "asdfgh") == negocio.mensaje_por_defecto


def test_wants_human(negocio) -> None:
    assert wants_human(negocio, "Quiero un HUMANO por favor")
    assert not wants_human(negocio, "hola")


def test_default_settings_use_rules(negocio) -> None:
    settings = Settings(_env_file=None)
    reply = asyncio.run(generate_reply(settings, negocio, "horario", []))
    assert reply.source == "rules"


def llm_settings(provider: str, **extra) -> Settings:
    return Settings(_env_file=None, brain="llm", llm_provider=provider, **extra)


def test_llm_without_key_falls_back_to_rules(negocio, sent_calls: list) -> None:
    reply = asyncio.run(generate_reply(llm_settings("openai"), negocio, "horario", []))
    assert reply.source == "rules" and "6:00" in reply.text
    assert sent_calls == []  # sin clave ni siquiera se intenta la llamada


def test_openai_reply(negocio, monkeypatch) -> None:
    calls = install_http_mock(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"choices": [{"message": {"content": " Abrimos a las 6. "}}]}
        ),
    )
    settings = llm_settings("openai", openai_api_key="sk-test")
    history = [{"role": "user", "content": "hola"}]
    reply = asyncio.run(generate_reply(settings, negocio, "¿horario?", history))
    assert (reply.source, reply.text) == ("llm", "Abrimos a las 6.")
    req = calls[0]
    assert req.headers["Authorization"] == "Bearer sk-test"
    sent = json.loads(req.content)
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][-1] == {"role": "user", "content": "¿horario?"}
    assert negocio.nombre in sent["messages"][0]["content"]


def test_anthropic_reply(negocio, monkeypatch) -> None:
    calls = install_http_mock(
        monkeypatch,
        lambda req: httpx.Response(
            200, json={"content": [{"type": "text", "text": "Hola desde Claude"}]}
        ),
    )
    settings = llm_settings("anthropic", anthropic_api_key="ak-test")
    reply = asyncio.run(generate_reply(settings, negocio, "hola", []))
    assert (reply.source, reply.text) == ("llm", "Hola desde Claude")
    req = calls[0]
    assert req.headers["x-api-key"] == "ak-test"
    assert "system" in json.loads(req.content)


@pytest.mark.parametrize(
    "handler",
    [
        lambda req: httpx.Response(500, json={"error": "boom"}),
        lambda req: httpx.Response(200, json={"unexpected": True}),
        lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]}),
    ],
    ids=["http-500", "json-inesperado", "respuesta-vacia"],
)
def test_llm_failures_fall_back_to_rules(negocio, monkeypatch, handler) -> None:
    install_http_mock(monkeypatch, handler)
    settings = llm_settings("openai", openai_api_key="sk-test")
    reply = asyncio.run(generate_reply(settings, negocio, "precio", []))
    assert reply.source == "rules" and "S/" in reply.text


def test_llm_error_does_not_leak_key(negocio, monkeypatch) -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fallo con sk-leak-123")

    install_http_mock(monkeypatch, boom)
    settings = llm_settings("openai", openai_api_key="sk-leak-123")
    with pytest.raises(LLMError) as exc:
        asyncio.run(reply_llm(settings, negocio, "hola", []))
    assert "sk-leak-123" not in str(exc.value)


def test_handoff_skips_llm(negocio, sent_calls: list) -> None:
    settings = llm_settings("openai", openai_api_key="sk-test")
    reply = asyncio.run(generate_reply(settings, negocio, "pásame con un humano", []))
    assert reply.source == "handoff" and sent_calls == []


def test_system_prompt_contains_faq(negocio) -> None:
    prompt = build_system_prompt(negocio)
    assert "Av. Los Olivos" in prompt and negocio.nombre in prompt
