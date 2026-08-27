"""Configuração da aplicação, carregada uma única vez e injetada onde for necessária."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Modelo padrão por provider, usado quando `LLM_MODEL` não é informado.
DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}


class Settings(BaseSettings):
    """Configuração lida de variáveis de ambiente e do arquivo `.env`."""

    # Trocar de provider é trocar esta variável. O agente não muda.
    llm_provider: Literal["openai", "ollama"] = "openai"

    # Vazio significa "use o padrão do provider escolhido"; ver `llm_model`.
    llm_model: str = ""

    # Opcional de propósito: a aplicação sobe e responde /health sem chave.
    # Só o /ask exige LLM, e falha com 503 explicativo em vez de quebrar no import.
    openai_api_key: SecretStr | None = None

    # Ollama roda local e não usa credencial; basta o servidor estar no ar.
    ollama_base_url: str = "http://localhost:11434"

    dataset_path: Path = Path("dataset/sales.csv")

    max_query_rows: int = 100
    max_agent_turns: int = 6
    llm_timeout_seconds: int = 30

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def _blank_key_means_unconfigured(cls, value: object) -> object:
        """Trata chave vazia como ausente.

        `docker compose` com `OPENAI_API_KEY=${OPENAI_API_KEY}` e a variável não
        definida no host injeta string vazia, não remove a variável. Sem isto o
        /health anunciaria `configured` e o /ask tentaria chamar o provider com
        credencial vazia, em vez de devolver o 503 explicativo.
        """
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_model", mode="before")
    @classmethod
    def _blank_model_means_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return ""
        return value

    @property
    def resolved_model(self) -> str:
        """Modelo efetivo: o configurado, ou o padrão do provider."""
        return self.llm_model or DEFAULT_MODELS[self.llm_provider]

    @property
    def llm_configured(self) -> bool:
        """Indica se o `/ask` tem como funcionar.

        Depende do provider: OpenAI exige credencial, Ollama exige apenas um
        servidor local — cuja indisponibilidade só aparece na primeira chamada,
        e vira `LLMError` (503), não um 500 opaco.
        """
        if self.llm_provider == "ollama":
            return True
        return self.openai_api_key is not None


@lru_cache
def get_settings() -> Settings:
    """Devolve a configuração, resolvida na primeira chamada e cacheada depois.

    Não é resolvida em import de módulo: quem chama é o `lifespan` da aplicação,
    o que mantém os testes livres para sobrescrever o ambiente antes.
    """
    return Settings()
