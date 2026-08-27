"""Contrato HTTP da aplicação."""

from typing import Any

from pydantic import BaseModel, Field

from app.agent.state import ToolTrace


class AskRequest(BaseModel):
    """Pergunta em linguagem natural sobre o dataset."""

    question: str = Field(min_length=1, max_length=1000, description="A pergunta a responder.")


class AskResponse(BaseModel):
    """Resposta do agente.

    `assumptions` e `warnings` ficam fora de `answer` de propósito: separados, eles
    são verificáveis por máquina — os evals da Fase 7 conseguem asseverar que o
    agente declarou a interpretação escolhida, o que seria impossível se isso
    estivesse diluído no texto.
    """

    answer: str
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Estado da aplicação."""

    status: str
    llm: str
    provider: str
    model: str
    dataset_rows: int


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


__all__ = [
    "AskRequest",
    "AskResponse",
    "ErrorBody",
    "ErrorResponse",
    "HealthResponse",
    "ToolTrace",
]
