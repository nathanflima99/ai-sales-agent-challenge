"""Construção do modelo de chat.

A abstração de provider vem do próprio LangChain: o resto da aplicação depende de
`BaseChatModel`, e nunca de uma implementação concreta. Trocar de provider é
trocar uma variável de ambiente — o `SalesAgent` não muda uma linha.

Dois providers hoje:

- **openai** — exige `OPENAI_API_KEY`.
- **ollama** — modelo local, sem chave e sem custo por token. Exige um servidor
  Ollama em execução e um modelo que suporte *tool calling*, porque o agente
  inteiro depende disso.
"""

import logging
from typing import Literal

from langchain_core.language_models import BaseChatModel

from app.config import Settings
from app.errors import LLMNotConfiguredError

logger = logging.getLogger(__name__)

Provider = Literal["openai", "ollama"]

#: Modelos Ollama sem suporte a tool calling não conseguem operar este agente:
#: sem tool call ele nunca consulta o DuckDB e não tem como responder.
TOOL_CALLING_HINT = (
    "The Ollama model must support tool calling (e.g. llama3.1, qwen2.5, mistral-nemo). "
    "Models without it cannot query the dataset."
)


def build_model(settings: Settings) -> BaseChatModel:
    """Instancia o modelo de chat a partir da configuração.

    Chamada no `lifespan` e injetada no agente: nenhum nó do grafo cria client
    próprio, o que duplicaria conexões e tornaria o agente impossível de testar
    sem rede.

    Raises:
        LLMNotConfiguredError: se o provider escolhido não estiver utilizável.
    """
    provider = settings.llm_provider

    if provider == "openai":
        model = _build_openai(settings)
    elif provider == "ollama":
        model = _build_ollama(settings)
    else:  # pragma: no cover - impedido pela validação do Settings
        raise LLMNotConfiguredError(f"Unknown LLM provider '{provider}'.")

    logger.info(
        "chat model ready",
        extra={"provider": provider, "model": settings.resolved_model},
    )
    return model


def _build_openai(settings: Settings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if settings.openai_api_key is None:
        raise LLMNotConfiguredError(
            "OPENAI_API_KEY is not set. Set it in .env, or switch to a local model "
            "with LLM_PROVIDER=ollama."
        )

    return ChatOpenAI(
        model=settings.resolved_model,
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        # Determinismo vale mais que criatividade: a tarefa é traduzir pergunta em
        # SQL, e variação aqui é ruído que os evals teriam de absorver.
        temperature=0,
    )


def _build_ollama(settings: Settings) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    logger.info(
        "using local ollama model",
        extra={"base_url": settings.ollama_base_url, "hint": TOOL_CALLING_HINT},
    )
    return ChatOllama(
        model=settings.resolved_model,
        base_url=settings.ollama_base_url,
        temperature=0,
    )
