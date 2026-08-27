"""Configuração da aplicação, carregada uma única vez e injetada onde for necessária."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuração lida de variáveis de ambiente e do arquivo `.env`."""

    # Opcional de propósito: a aplicação sobe e responde /health sem chave.
    # Só o /ask exige LLM, e falha com 503 explicativo em vez de quebrar no import.
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"

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

    @property
    def llm_configured(self) -> bool:
        """Indica se há credencial de LLM disponível."""
        return self.openai_api_key is not None


@lru_cache
def get_settings() -> Settings:
    """Devolve a configuração, resolvida na primeira chamada e cacheada depois.

    Não é resolvida em import de módulo: quem chama é o `lifespan` da aplicação,
    o que mantém os testes livres para sobrescrever o ambiente antes.
    """
    return Settings()
