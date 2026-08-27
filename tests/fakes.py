"""Modelo de chat falso para testar o agente sem rede e sem tokens.

`FakeMessagesListChatModel` do langchain-core não implementa `bind_tools`, que é
exatamente o que o agente usa, então o fake precisa ser nosso.
"""

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class ScriptedChatModel(BaseChatModel):
    """Devolve respostas pré-programadas, uma por chamada."""

    responses: list[AIMessage] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> BaseChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("ScriptedChatModel ficou sem respostas programadas")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


class ExplodingChatModel(BaseChatModel):
    """Simula indisponibilidade do provider."""

    @property
    def _llm_type(self) -> str:
        return "exploding"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> BaseChatModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise TimeoutError("provider unreachable")


def tool_call(name: str, args: dict[str, Any], call_id: str = "call_1") -> AIMessage:
    """AIMessage pedindo uma chamada de ferramenta."""
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )
