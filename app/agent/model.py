"""Construção do modelo de chat.

A abstração de provider vem do próprio LangChain: o resto da aplicação depende de
`BaseChatModel`, e nunca de uma implementação concreta. Trocar de provider é trocar
variáveis de ambiente — o `SalesAgent` não muda uma linha.

Dois providers hoje:

- **openai** — exige `OPENAI_API_KEY`.
- **ollama** — pode usar servidor local sem chave ou a API hospedada em
  `https://ollama.com` com `OLLAMA_API_KEY`. O modelo precisa suportar *tool calling*,
  porque o agente inteiro depende disso.
"""

import logging
from collections.abc import Generator
from typing import Literal

import httpx
from langchain_core.language_models import BaseChatModel
from pydantic import SecretStr

from app.config import Settings
from app.errors import LLMNotConfiguredError

logger = logging.getLogger(__name__)

Provider = Literal["openai", "ollama"]


class BearerAuth(httpx.Auth):
    """Injeta `Authorization: Bearer` sem guardar o token em texto plano.

    Passar `client_kwargs={"headers": {...}}` funciona, mas materializa a chave
    numa string comum dentro do `ChatOllama` — e ela reaparece em `repr(model)`,
    anulando a proteção que o `SecretStr` dá ao `Settings`. Bastaria um
    `logger.debug` com o objeto, ou o modo verboso do LangChain, para vazá-la.

    Mantendo o `SecretStr` aqui dentro, o token só é materializado no momento de
    assinar a requisição, e o `repr` desta classe não o expõe.
    """

    def __init__(self, token: SecretStr) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token.get_secret_value()}"
        yield request

    def __repr__(self) -> str:
        return "<BearerAuth masked>"


#: Modelos Ollama sem suporte a tool calling não conseguem operar este agente:
#: sem tool call ele nunca consulta o DuckDB e não tem como responder.
TOOL_CALLING_HINT = (
    "The Ollama model must support tool calling (check `ollama show <model>` for the "
    "'tools' capability; qwen3.5, qwen2.5 and mistral-nemo have it, gemma3 does not). "
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
        extra={
            "provider": provider,
            "model": settings.resolved_model,
            "thinking": settings.ollama_thinking if provider == "ollama" else None,
        },
    )
    return model


def _build_openai(settings: Settings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    if settings.openai_api_key is None:
        raise LLMNotConfiguredError(
            "OPENAI_API_KEY is not set. Set it in .env, or switch to local Ollama "
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

    if settings.ollama_is_direct_cloud and settings.ollama_api_key is None:
        raise LLMNotConfiguredError(
            "OLLAMA_API_KEY is required when OLLAMA_BASE_URL points to https://ollama.com."
        )

    # O ChatOllama não expõe `timeout`; o valor vai pelo cliente httpx que ele
    # constrói. Sem isto, `LLM_TIMEOUT_SECONDS` valeria só para a OpenAI, e uma
    # requisição pendurada seguraria uma thread do pool do FastAPI sem limite.
    client_kwargs: dict[str, object] = {"timeout": settings.llm_timeout_seconds}
    if settings.ollama_api_key is not None:
        client_kwargs["auth"] = BearerAuth(settings.ollama_api_key)

    # `reasoning` tem três estados no langchain-ollama, e eles NÃO são apenas
    # ligado/desligado:
    #
    #   False     -> envia `think: false`. O modelo não raciocina.
    #   True      -> envia `think: true` E separa o raciocínio num campo próprio,
    #                `additional_kwargs["reasoning_content"]`.
    #   ausente   -> o Ollama usa o comportamento nativo do modelo, com o
    #                raciocínio inline no conteúdo.
    #
    # Passar `True` parece o caminho óbvio para "ligar o thinking" e é o pior dos
    # três aqui. Medido com `qwen3.5:4b`: uma pergunta de uma frase gerou 22.190
    # caracteres de `reasoning_content`. Num agente, cada turno acumula esse bloco
    # no histórico, e a partir do terceiro ou quarto o modelo passa a devolver
    # conteúdo vazio. O golden set caiu de 8/8 (ausente) para 5/8 (`True`), com as
    # três falhas sendo exatamente respostas vazias.
    #
    # Por isso "ligado" aqui é `None`, que é o default do campo e equivale a não
    # passar nada.
    reasoning = None if settings.ollama_thinking else False

    logger.info(
        "using ollama model",
        extra={
            "base_url": settings.ollama_base_url,
            "authenticated": settings.ollama_api_key is not None,
            "thinking": settings.ollama_thinking,
            "reasoning_param": reasoning,
            "hint": TOOL_CALLING_HINT,
        },
    )
    return ChatOllama(
        model=settings.resolved_model,
        base_url=settings.ollama_base_url,
        temperature=0,
        reasoning=reasoning,
        # Ollama Cloud expects Authorization: Bearer <OLLAMA_API_KEY>.
        client_kwargs=client_kwargs,
    )
