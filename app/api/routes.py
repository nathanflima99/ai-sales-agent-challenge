"""Rotas HTTP.

A camada é fina de propósito: validar entrada, chamar o agente, traduzir o
resultado. Nenhuma regra de negócio e nenhum SQL moram aqui.
"""

import logging
import time

from fastapi import APIRouter, Request

from app.agent.graph import SalesAgent
from app.analytics.profiling import DatasetProfile
from app.config import Settings
from app.errors import LLMNotConfiguredError
from app.logging_setup import request_id_var
from app.schemas import AskRequest, AskResponse, ErrorResponse, HealthResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["ops"])
def health(request: Request) -> HealthResponse:
    """Healthcheck independente do LLM.

    Responde `ok` mesmo sem `OPENAI_API_KEY`; o campo `llm` diz se o `/ask` vai
    conseguir funcionar. Isso mantém o container observável e a UI carregável em
    um clone sem credencial.
    """
    settings: Settings = request.app.state.settings
    profile: DatasetProfile = request.app.state.profile
    return HealthResponse(
        status="ok",
        llm="configured" if settings.llm_configured else "unconfigured",
        provider=settings.llm_provider,
        model=settings.resolved_model,
        dataset_rows=profile.row_count,
    )


@router.post(
    "/ask",
    response_model=AskResponse,
    tags=["agent"],
    responses={
        400: {"model": ErrorResponse},
        503: {"model": ErrorResponse, "description": "LLM indisponível ou não configurado"},
    },
)
def ask(request: Request, payload: AskRequest) -> AskResponse:
    """Responde uma pergunta em linguagem natural sobre o dataset.

    Handler síncrono de propósito: o agente é bloqueante, e o FastAPI despacha
    handlers `def` num threadpool. Declará-lo `async` prenderia o event loop
    durante toda a conversa com o modelo.
    """
    agent: SalesAgent | None = request.app.state.agent
    if agent is None:
        raise LLMNotConfiguredError(
            "OPENAI_API_KEY is not set, so questions cannot be answered. "
            "Set it in .env or pass it to the container and restart."
        )

    started = time.perf_counter()
    logger.info("question received", extra={"question": payload.question})

    result = agent.run(payload.question)
    total_ms = (time.perf_counter() - started) * 1000

    return AskResponse(
        answer=result.answer,
        assumptions=result.assumptions,
        warnings=result.warnings,
        metadata={
            "request_id": request_id_var.get(),
            "turns": result.turns,
            "total_ms": round(total_ms, 2),
            # Único fato verificável sobre a fundamentação da resposta: houve ao
            # menos uma consulta bem-sucedida ao dataset. Recusas e perguntas de
            # escopo legitimamente não consultam, então isto informa em vez de
            # bloquear.
            "data_queried": result.data_queried,
            # O trace é o recurso mais útil desta resposta: mostra o SQL exato que
            # o agente escreveu, então qualquer número pode ser reconferido à mão.
            "trace": [entry.model_dump() for entry in result.trace],
        },
    )
