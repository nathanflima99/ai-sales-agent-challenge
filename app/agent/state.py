"""Estado do grafo do agente."""

import operator
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from app.agent.tools import FinalAnswer


class ToolTrace(BaseModel):
    """Registro de uma chamada de ferramenta.

    Exposto na resposta da API: é o que permite ao leitor conferir de onde veio
    cada número, incluindo o SQL exato que o agente escreveu.
    """

    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error"]
    elapsed_ms: float | None = None
    sql: str | None = None
    row_count: int | None = None
    cache_hit: bool | None = None
    error: str | None = None


class AgentState(TypedDict):
    """Estado que atravessa o grafo.

    `messages` acumula pelo reducer do LangGraph; `trace` acumula por concatenação.
    `turns` conta chamadas ao modelo e é a trava principal contra loop infinito.
    """

    #: A pergunta original. Números que já vinham dela não contam como cálculo
    #: do modelo na verificação final.
    question: str

    messages: Annotated[list[AnyMessage], add_messages]
    turns: int
    trace: Annotated[list[ToolTrace], operator.add]
    final: FinalAnswer | None

    #: Todo número que alguma consulta devolveu, normalizado para sequência de
    #: dígitos. É contra este conjunto que a resposta final é verificada: um
    #: número que não está aqui não veio do banco, veio da cabeça do modelo.
    result_numbers: Annotated[list[str], operator.add]
