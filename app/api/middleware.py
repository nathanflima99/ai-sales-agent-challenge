"""Middleware de rastreabilidade."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

from app.logging_setup import request_id_var

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Atribui um `request_id`, mede a duração e devolve o id no header.

    O id vai para um `ContextVar` lido pelo formatter de log, então toda linha
    emitida durante o request — inclusive dentro do repositório e do agente — sai
    correlacionada, sem que nenhuma dessas camadas precise conhecer o id.
    """
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
    token = request_id_var.set(request_id)
    started = time.perf_counter()

    try:
        response = await call_next(request)
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "request completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round(elapsed_ms, 2),
            },
        )
        request_id_var.reset(token)

    response.headers[REQUEST_ID_HEADER] = request_id
    return response
