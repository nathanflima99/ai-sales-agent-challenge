"""Logging estruturado em JSON, com `request_id` propagado por contextvars.

O `request_id` fica num `ContextVar` em vez de ser passado de parâmetro em parâmetro
por toda a stack: o middleware HTTP o define uma vez por request e o formatter o lê
de onde estiver, sem que repositório, guard ou agente precisem conhecê-lo.
"""

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Atributos que o logging já coloca em todo LogRecord; qualquer outro veio de
# `logger.info(..., extra={...})` e por isso entra no JSON final.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Serializa o LogRecord como uma linha JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Instala o formatter JSON no root logger, substituindo handlers anteriores."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # O uvicorn instala handlers próprios; deixá-los propagar para o root evita
    # duas linhas com formatos diferentes para o mesmo evento.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
