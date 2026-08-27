"""Construção do modelo de chat.

A abstração de provider vem do próprio LangChain: o resto da aplicação depende de
`BaseChatModel`, não de `ChatOpenAI`. Trocar de provider é trocar esta factory —
não há `Protocol` próprio aqui porque seria reimplementar o que a biblioteca já dá.
"""

import logging

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.errors import LLMNotConfiguredError

logger = logging.getLogger(__name__)


def build_model(settings: Settings) -> BaseChatModel:
    """Instancia o modelo de chat a partir da configuração.

    Chamada no `lifespan` e injetada no grafo: nenhum nó cria client próprio, o que
    manteria conexões duplicadas e tornaria o agente impossível de testar sem rede.

    Raises:
        LLMNotConfiguredError: se não houver credencial configurada.
    """
    if settings.openai_api_key is None:
        raise LLMNotConfiguredError(
            "OPENAI_API_KEY is not set. Configure it in .env or pass it to the container."
        )

    logger.info("building chat model", extra={"model": settings.openai_model})
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        # Determinismo é mais valioso que criatividade: a tarefa é traduzir pergunta
        # em SQL, e variação aqui é ruído que os evals da Fase 7 teriam de absorver.
        temperature=0,
    )
