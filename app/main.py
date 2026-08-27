"""Fábrica da aplicação FastAPI."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent.graph import SalesAgent
from app.agent.model import build_model
from app.agent.tools import build_tools
from app.analytics.profiling import build_profile
from app.analytics.repository import AnalyticsRepository
from app.api.middleware import request_context_middleware
from app.api.routes import router
from app.config import get_settings
from app.errors import AppError
from app.logging_setup import setup_logging

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Abre os recursos da aplicação e os guarda em `app.state`.

    Nada é instanciado em import de módulo: conexão DuckDB, modelo e agente nascem
    aqui, uma vez, e são injetados. Sem `OPENAI_API_KEY` a aplicação sobe do mesmo
    jeito, apenas sem agente — `/health` responde e a UI carrega.
    """
    settings = get_settings()
    setup_logging(settings.log_level)

    repository = AnalyticsRepository.open(settings.dataset_path)
    profile = build_profile(repository.connection)

    agent: SalesAgent | None = None
    if settings.llm_configured:
        tools = build_tools(repository, profile, settings)
        agent = SalesAgent(build_model(settings), tools, profile, settings)
    else:
        logger.warning("OPENAI_API_KEY is not set; /ask will return 503")

    app.state.settings = settings
    app.state.repository = repository
    app.state.profile = profile
    app.state.agent = agent

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
    """Monta a aplicação com rotas, middleware e tratamento de erros."""
    app = FastAPI(
        title="AI Sales Agent",
        description=(
            "Agente de IA que responde perguntas em linguagem natural sobre sales.csv. "
            "O modelo interpreta e narra; o DuckDB calcula."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.middleware("http")(request_context_middleware)

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
        """Última barreira: registra o traceback e devolve um corpo genérico."""
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )

    app.include_router(router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
