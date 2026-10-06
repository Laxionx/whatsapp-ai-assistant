"""Configuración desde variables de entorno (pydantic-settings)."""

from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # WhatsApp Cloud API
    whatsapp_verify_token: SecretStr = SecretStr("")
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_access_token: SecretStr = SecretStr("")
    whatsapp_phone_number_id: str = ""
    graph_api_version: str = "v23.0"
    graph_api_base: str = "https://graph.facebook.com"

    # Administración
    admin_token: SecretStr = SecretStr("")

    # Cerebro: "rules" (FAQ) o "llm" (con vuelta a reglas si falla)
    brain: Literal["rules", "llm"] = "rules"
    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: SecretStr = SecretStr("")
    anthropic_model: str = "claude-haiku-4-5"
    llm_timeout_seconds: float = 15.0

    # Datos
    negocio_path: Path = Path("config/negocio.yaml")
    db_path: Path = Path("data/conversaciones.db")

    @property
    def can_send(self) -> bool:
        """Sin token o phone id no se llama a Meta (modo local)."""
        return bool(self.whatsapp_access_token.get_secret_value() and self.whatsapp_phone_number_id)

    @property
    def llm_api_key(self) -> str:
        key = self.openai_api_key if self.llm_provider == "openai" else self.anthropic_api_key
        return key.get_secret_value()
