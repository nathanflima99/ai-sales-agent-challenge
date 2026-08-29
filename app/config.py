"""Configuração da aplicação, carregada uma única vez e injetada onde for necessária."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Modelo padrão por provider, usado quando `LLM_MODEL` não é informado.
#: O padrão do Ollama é o modelo efetivamente validado ponta a ponta contra este
#: dataset — ver a seção de validação do README. Um default não exercitado seria
#: um convite a falhar na primeira execução de quem clona o repositório.
DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4o-mini",
    "ollama": "qwen3.5:4b",
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

    # Ollama local não exige credencial. Para acesso direto a https://ollama.com,
    # a API key é enviada como Authorization: Bearer <key>.
    ollama_base_url: str = "http://localhost:11434"
    ollama_api_key: SecretStr | None = None

    # Qwen 3.5 suporta reasoning/thinking, e aqui ele fica LIGADO por padrão.
    #
    # A intuição diz o contrário — o cálculo é do DuckDB, então o modelo só
    # precisaria narrar. O golden set mediu e desmentiu: com `qwen3.5:4b`,
    # desligar leva a taxa de acerto de 8/8 para 3/8, enquanto o tempo médio cai
    # de 122s para 53s. O SQL continua correto; o que degrada é justamente
    # interpretar e narrar. Num caso o modelo obteve os dois totais certos e
    # errou a subtração na resposta.
    #
    # Desligue apenas quando latência valer mais que corretude, cientes do custo.
    ollama_thinking: bool = True

    dataset_path: Path = Path("dataset/sales.csv")

    max_query_rows: int = 100

    # 6 foi dimensionado quando o agente só tinha o retry de ferramenta. Depois
    # entraram o retry de resposta vazia e o de verificação de números, e os três
    # consomem do mesmo orçamento — a cota para trabalho útil encolheu sem o
    # número ser reajustado. Medido: a pergunta de promoções, que já gastava 6
    # turnos no melhor caso, estourou 10 quando os três dispararam na mesma
    # execução.
    #
    # 15, e não 12, porque foi com 15 que as três rodadas de 8/8 do golden set
    # foram medidas. O maior consumo observado ali foi 6 turnos, então 12
    # provavelmente bastaria — mas o default precisa ser a configuração medida,
    # não uma que parece suficiente.
    max_agent_turns: int = 15
    llm_timeout_seconds: int = 30

    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("openai_api_key", "ollama_api_key", mode="before")
    @classmethod
    def _blank_key_means_unconfigured(cls, value: object) -> object:
        """Trata chave vazia como ausente.

        `docker compose` com uma variável não definida no host pode injetar string
        vazia. Sem normalização, health/configuração poderiam anunciar credencial
        existente mesmo quando não há chave utilizável.
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
    def ollama_is_direct_cloud(self) -> bool:
        """Indica acesso direto à API autenticada hospedada em ollama.com."""
        return (urlparse(self.ollama_base_url).hostname or "").lower() == "ollama.com"

    @property
    def llm_configured(self) -> bool:
        """Indica se o `/ask` tem como funcionar com a configuração declarada.

        OpenAI sempre exige credencial. Ollama local pode operar sem chave; acesso
        direto a ollama.com exige `OLLAMA_API_KEY`.
        """
        if self.llm_provider == "ollama":
            return not self.ollama_is_direct_cloud or self.ollama_api_key is not None
        return self.openai_api_key is not None


@lru_cache
def get_settings() -> Settings:
    """Devolve a configuração, resolvida na primeira chamada e cacheada depois.

    Não é resolvida em import de módulo: quem chama é o `lifespan` da aplicação,
    o que mantém os testes livres para sobrescrever o ambiente antes.
    """
    return Settings()
