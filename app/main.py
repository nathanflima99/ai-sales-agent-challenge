"""Fábrica da aplicação FastAPI."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.errors import AppError
from app.logging_setup import setup_logging

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Resposta do healthcheck."""

    status: Literal["ok"]
    llm: Literal["configured", "unconfigured"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Resolve a configuração e prepara o logging no start da aplicação.

    Nenhum recurso é criado em import de módulo: a conexão DuckDB (Fase 2) e o
    client de LLM (Fase 4) serão abertos aqui e guardados em `app.state`.
    """
    settings = get_settings()
    setup_logging(settings.log_level)

    app.state.settings = settings

    logger.info(
        "application startup",
        extra={"llm_configured": settings.llm_configured, "model": settings.openai_model},
    )
    yield
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

        Quem decide se a mensagem é pública é a própria exceção, via
        `expose_message`: 4xx expõe, 5xx esconde, e casos como
        `LLMNotConfiguredError` sobrescrevem porque a mensagem é a instrução de
        configuração. O detalhe completo vai sempre para o log.
        """
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
                    "message": exc.message if exc.expose_message else "Internal server error",
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
        return HealthResponse(
            status="ok",
            llm="configured" if settings.llm_configured else "unconfigured",
        )

    return app


app = create_app()
