"""Cerebro (b): LLM opcional (OpenAI o Anthropic) vía HTTP directo."""

from app import http
from app.config import Settings
from app.negocio import Negocio

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MAX_TOKENS = 300


class LLMError(Exception):
    """Cualquier fallo del proveedor; el llamador vuelve a las reglas."""


def build_system_prompt(negocio: Negocio) -> str:
    faq = "\n".join(f"- {', '.join(e.claves)}: {e.respuesta}" for e in negocio.faq)
    return (
        f"Eres el asistente de WhatsApp de {negocio.nombre}. {negocio.descripcion}\n"
        "Responde en español, breve y amable, usando SOLO esta información. "
        "Si no sabes algo, dilo y ofrece derivar a una persona.\n"
        f"Información del negocio:\n{faq}"
    )


async def _call(settings: Settings, system: str, messages: list[dict[str, str]]) -> str:
    key = settings.llm_api_key
    async with http.make_client(settings.llm_timeout_seconds) as client:
        if settings.llm_provider == "openai":
            resp = await client.post(
                OPENAI_URL,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": settings.openai_model,
                    "max_tokens": MAX_TOKENS,
                    "messages": [{"role": "system", "content": system}, *messages],
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        resp = await client.post(
            ANTHROPIC_URL,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={
                "model": settings.anthropic_model,
                "max_tokens": MAX_TOKENS,
                "system": system,
                "messages": messages,
            },
        )
        resp.raise_for_status()
        return resp.json()["content"][0]["text"]


async def reply_llm(
    settings: Settings, negocio: Negocio, text: str, history: list[dict[str, str]]
) -> str:
    """Pide la respuesta al LLM; lanza LLMError si no hay clave o algo falla."""
    if not settings.llm_api_key:
        raise LLMError("sin API key")
    messages = [*history, {"role": "user", "content": text}]
    try:
        answer = await _call(settings, build_system_prompt(negocio), messages)
    except Exception as exc:  # red, HTTP o JSON inesperado
        # Solo el tipo de error: el mensaje podría contener cabeceras o claves.
        raise LLMError(type(exc).__name__) from exc
    if not answer or not answer.strip():
        raise LLMError("respuesta vacía")
    return answer.strip()
