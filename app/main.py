"""Fábrica da aplicação FastAPI."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.analytics.profiling import DatasetProfile, build_profile
from app.analytics.repository import AnalyticsRepository
from app.config import Settings, get_settings
from app.errors import AppError
from app.logging_setup import setup_logging

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Resposta do healthcheck."""

    status: Literal["ok"]
    llm: Literal["configured", "unconfigured"]
    dataset_rows: int


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Resolve a configuração e prepara o logging no start da aplicação.

    Nenhum recurso é criado em import de módulo: a conexão DuckDB (Fase 2) e o
    client de LLM (Fase 4) serão abertos aqui e guardados em `app.state`.
    """
    settings = get_settings()
    setup_logging(settings.log_level)

    app.state.settings = settings

    # Dataset ausente ou com schema incompatível derruba o startup com mensagem
    # nomeando o problema, em vez de falhar na primeira pergunta do usuário.
    repository = AnalyticsRepository.open(settings.dataset_path)
    profile = build_profile(repository.connection)

    app.state.repository = repository
    app.state.profile = profile

    logger.info(
        "application startup",
        extra={
            "llm_configured": settings.llm_configured,
            "model": settings.openai_model,
            "dataset_rows": profile.row_count,
        },
    )
    try:
        yield
    finally:
        repository.close()
        logger.info("application shutdown")


def create_app() -> FastAPI:
    """Monta a aplicação com rotas e tratamento de erros."""
    app = FastAPI(
        title="AI Sales Agent",
        description="Agente de IA que responde perguntas em linguagem natural sobre sales.csv",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """Traduz falhas de domínio para HTTP, sem expor detalhes internos.

        A mensagem só é devolvida ao cliente em erros 4xx, onde ela é acionável —
        o guard de SQL, por exemplo, depende de explicar o que rejeitou. Em 5xx a
        mensagem pode carregar caminho de arquivo ou detalhe de infraestrutura, então
        vai apenas para o log e o cliente recebe um texto genérico.
        """
        is_server_error = exc.status_code >= 500
        logger.warning(
            "handled application error",
            extra={
                "error_code": exc.code,
                "status_code": exc.status_code,
                "detail": exc.message,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": "Internal server error" if is_server_error else exc.message,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """Última barreira: registra o traceback e devolve um corpo genérico.

        O stack trace vai para o log estruturado, nunca para o cliente.
        """
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )

    @app.get("/health", response_model=HealthResponse, tags=["ops"])
    def health(request: Request) -> HealthResponse:
        """Healthcheck independente do LLM.

        Responde `ok` mesmo sem `OPENAI_API_KEY`; o campo `llm` diz se o `/ask`
        conseguirá funcionar.
        """
        settings: Settings = request.app.state.settings
        profile: DatasetProfile = request.app.state.profile
        return HealthResponse(
            status="ok",
            llm="configured" if settings.llm_configured else "unconfigured",
            dataset_rows=profile.row_count,
        )

    return app


app = create_app()
