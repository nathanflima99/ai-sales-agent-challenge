"""Grafo LangGraph do agente.

O ciclo é `pensar -> agir -> observar -> replanejar`. O que torna isto um agente,
e não um tradutor de texto para SQL, é o passo de observar: quando uma ferramenta
falha, o erro volta para o modelo como `ToolMessage` e ele tenta de novo, em vez
de o usuário receber um 400.

Grafo explícito em vez do `create_react_agent` pronto: o trace de cada chamada, a
cota de turnos e o tratamento de erro de ferramenta precisam ser código nosso,
porque são exatamente o que a aplicação expõe e o que precisamos poder explicar.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, StateGraph

from app.agent.prompts import build_system_prompt
from app.agent.state import AgentState, ToolTrace
from app.agent.tools import SUBMIT_ANSWER, FinalAnswer, normalize_text_list
from app.agent.verification import correction_message, numbers_in_payload, unverified_numbers
from app.analytics.profiling import DatasetProfile
from app.config import Settings
from app.errors import AgentLoopError, AppError, LLMError

logger = logging.getLogger(__name__)

_RETRY_HINT = "Fix the problem described above and call the tool again."

#: Enviado quando o modelo devolve uma mensagem completamente vazia.
EMPTY_RESPONSE_NUDGE = (
    "Your last message was empty. Please continue: either call a tool to query "
    "the dataset, or call submit_answer with your final response."
)

#: Registrado em `warnings` quando o modelo encerra em prosa, sem a tool de saída.
#: A informação existia só no trace; aqui ela chega a quem lê apenas a resposta.
FALLBACK_WARNING = (
    "The model returned a final response without using the structured submit_answer tool."
)


@dataclass(slots=True)
class AgentResult:
    """Resultado de uma execução completa do agente."""

    answer: str
    assumptions: list[str]
    warnings: list[str]
    trace: list[ToolTrace]
    turns: int
    #: Verdadeiro apenas se houve ao menos um `query_sales_data` bem-sucedido.
    #: Nomeado pelo que conseguimos provar: que o dataset foi consultado. Não
    #: afirma que a resposta está correta, nem que usou o resultado da consulta.
    data_queried: bool = False


class SalesAgent:
    """Agente que responde perguntas sobre o dataset de vendas."""

    def __init__(
        self,
        model: BaseChatModel,
        tools: list[BaseTool],
        profile: DatasetProfile,
        settings: Settings,
    ) -> None:
        self._tools_by_name = {tool.name: tool for tool in tools}
        self._model = model.bind_tools(tools)
        self._system_prompt = build_system_prompt(profile)
        self._settings = settings
        self._graph = self._build_graph()

    # -- nós ---------------------------------------------------------------

    def _agent_node(self, state: AgentState) -> dict[str, Any]:
        """Chama o modelo. É aqui que a cota de turnos é aplicada."""
        if state["turns"] >= self._settings.max_agent_turns:
            raise AgentLoopError(
                f"The agent did not converge within {self._settings.max_agent_turns} turns."
            )

        try:
            response = self._model.invoke(state["messages"])
        except AppError:
            raise
        except Exception as exc:  # falha de rede, timeout, erro do provider
            logger.exception("llm call failed")
            raise LLMError("The language model is unavailable right now.") from exc

        return {"messages": [response], "turns": state["turns"] + 1}

    def _tools_node(self, state: AgentState) -> dict[str, Any]:
        """Executa as ferramentas pedidas, transformando falha em observação.

        Nenhuma exceção de domínio escapa daqui: ela vira conteúdo de `ToolMessage`
        e volta para o modelo corrigir. É o self-correction.
        """
        last = state["messages"][-1]
        if not isinstance(last, AIMessage):
            return {}

        messages: list[BaseMessage] = []
        traces: list[ToolTrace] = []
        seen_numbers: list[str] = []

        for call in last.tool_calls:
            name = call["name"]
            args = call["args"]
            call_id = call.get("id") or ""
            started = time.perf_counter()

            tool = self._tools_by_name.get(name)
            if tool is None:
                error = f"Unknown tool {name!r}. Available: {', '.join(self._tools_by_name)}"
                traces.append(ToolTrace(name=name, args=args, status="error", error=error))
                messages.append(ToolMessage(content=error, tool_call_id=call_id, status="error"))
                continue

            try:
                output = tool.invoke(args)
            except AppError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                traces.append(
                    ToolTrace(
                        name=name,
                        args=args,
                        status="error",
                        elapsed_ms=round(elapsed, 2),
                        error=exc.message,
                    )
                )
                messages.append(
                    ToolMessage(
                        content=f"{exc.message}\n{_RETRY_HINT}",
                        tool_call_id=call_id,
                        status="error",
                    )
                )
                logger.info("tool failed, returning error to the model", extra={"tool": name})
                continue

            elapsed = (time.perf_counter() - started) * 1000
            payload = output if isinstance(output, dict) else {"result": output}
            traces.append(
                ToolTrace(
                    name=name,
                    args=args,
                    status="ok",
                    elapsed_ms=round(elapsed, 2),
                    sql=payload.get("sql"),
                    row_count=payload.get("row_count"),
                    cache_hit=payload.get("cache_hit"),
                )
            )
            # Guardar os números que a consulta devolveu é o que permite, no fim,
            # verificar se a resposta citou apenas valores rastreáveis.
            seen_numbers.extend(numbers_in_payload(payload))
            messages.append(ToolMessage(content=str(payload), tool_call_id=call_id))

        return {"messages": messages, "trace": traces, "result_numbers": seen_numbers}

    def _finish_node(self, state: AgentState) -> dict[str, Any]:
        """Extrai a resposta final.

        O caminho normal é o modelo ter chamado `submit_answer`. Se ele responder em
        prosa, a resposta é aproveitada mesmo assim e a ocorrência fica registrada no
        trace: recusar-se a responder por uma formalidade seria pior para quem
        perguntou do que entregar sem `assumptions`.
        """
        last = state["messages"][-1]
        if isinstance(last, AIMessage):
            for call in last.tool_calls:
                if call["name"] == SUBMIT_ANSWER:
                    args = call["args"]
                    # Normalização defensiva: modelos pequenos mandam string ou
                    # objeto onde o schema pede lista. Ver `normalize_text_list`.
                    final = FinalAnswer(
                        answer=str(args.get("answer", "")),
                        assumptions=normalize_text_list(args.get("assumptions")),
                        warnings=normalize_text_list(args.get("warnings")),
                    )
                    return self._verify(state, final, args)

        logger.warning("model finished without calling submit_answer")
        text = _text_of(last).strip() if isinstance(last, AIMessage) else ""

        if not text:
            # Só chega aqui quando a cota de turnos acabou antes de o modelo
            # produzir qualquer coisa: o caminho normal para resposta vazia é o
            # nó `recover`, que pede outra tentativa. Devolver 200 com `answer` em
            # branco seria anunciar sucesso sem entregar resposta.
            logger.warning("model produced neither a tool call nor any text")
            return {
                "trace": [
                    ToolTrace(
                        name=SUBMIT_ANSWER,
                        status="error",
                        error="Model returned an empty response with no tool call.",
                    )
                ]
            }

        return {
            "final": FinalAnswer(answer=text, assumptions=[], warnings=[FALLBACK_WARNING]),
            "trace": [
                ToolTrace(
                    name=SUBMIT_ANSWER,
                    status="error",
                    error="Model answered without calling submit_answer.",
                )
            ],
        }

    def _verify(
        self, state: AgentState, final: FinalAnswer, args: dict[str, Any]
    ) -> dict[str, Any]:
        """Confere que todo número da resposta veio de uma consulta.

        Esta é a trava que faltava. A regra "o DuckDB calcula" vivia apenas no
        prompt, e instrução é seguida de forma probabilística: perguntado pela
        diferença entre planejado e realizado, o modelo consultou as duas somas e
        subtraiu na resposta, errando o valor em 10.000 e o sinal.

        Quando um número não é rastreável, ele volta ao modelo como observação,
        no mesmo mecanismo que trata SQL rejeitado. A cota de turnos limita as
        tentativas.

        Esgotada a cota, a resposta é entregue com um aviso explícito em vez de
        virar erro: uma resposta possivelmente imprecisa, marcada como tal, é
        melhor para quem perguntou do que um 500.
        """
        unverified = unverified_numbers(
            final.answer, state["question"], set(state["result_numbers"])
        )
        if not unverified:
            return {
                "final": final,
                "trace": [ToolTrace(name=SUBMIT_ANSWER, args=args, status="ok")],
            }

        trace = ToolTrace(
            name="number_check",
            status="error",
            error=f"Numbers not found in any query result: {', '.join(unverified)}",
        )

        if state["turns"] < self._settings.max_agent_turns:
            logger.warning(
                "answer cites numbers no query returned, asking for a correction",
                extra={"unverified": unverified, "turns": state["turns"]},
            )
            return {
                "messages": [HumanMessage(content=correction_message(unverified))],
                "trace": [trace],
            }

        logger.warning(
            "answer cites unverified numbers and the turn budget is over",
            extra={"unverified": unverified},
        )
        final.warnings.append(
            "Alguns números desta resposta não foram encontrados em nenhum "
            f"resultado de consulta ({', '.join(unverified)}) e podem ter sido "
            "calculados pelo modelo."
        )
        return {"final": final, "trace": [trace]}

    def _recover_node(self, state: AgentState) -> dict[str, Any]:
        """Pede outra tentativa quando o modelo devolve uma mensagem vazia.

        Medido com `qwen3.5:4b`: em 6 de 32 execuções o modelo respondeu sem tool
        call, sem texto e sem raciocínio, literalmente nada. É transitório: a
        mesma pergunta funciona na tentativa seguinte, e das 26 execuções que
        produziram resposta, 26 estavam corretas.

        Tratar isso como falha terminal descartava ~19% das perguntas por um
        soluço do modelo. Aqui vira mais um caso de self-correction, com a cota
        de turnos servindo de limite como já servia para erro de ferramenta.

        O nudge existe para o contexto mudar: com `temperature=0`, reenviar
        exatamente o mesmo histórico convida exatamente a mesma resposta.
        """
        logger.warning("empty model response, asking again", extra={"turns": state["turns"]})
        return {
            "messages": [HumanMessage(content=EMPTY_RESPONSE_NUDGE)],
            "trace": [
                ToolTrace(
                    name="model_retry",
                    status="error",
                    error="Model returned an empty response; asking again.",
                )
            ],
        }

    # -- roteamento --------------------------------------------------------

    @staticmethod
    def _route(state: AgentState) -> str:
        last = state["messages"][-1]

        if not isinstance(last, AIMessage) or not last.tool_calls:
            # Sem tool call, ou o modelo respondeu em prosa, e aí a prosa vale
            # como resposta, ou não respondeu nada, e aí vale tentar de novo.
            # Voltar direto ao nó do modelo alternaria entre os dois sem nada
            # mudar no contexto; o nó `recover` acrescenta o pedido explícito.
            if isinstance(last, AIMessage) and not _text_of(last).strip():
                return "recover"
            return "finish"

        if any(call["name"] == SUBMIT_ANSWER for call in last.tool_calls):
            return "finish"
        return "tools"

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._tools_node)
        graph.add_node("finish", self._finish_node)

        graph.add_node("recover", self._recover_node)

        graph.set_entry_point("agent")
        graph.add_conditional_edges(
            "agent",
            self._route,
            {"tools": "tools", "finish": "finish", "recover": "recover"},
        )
        graph.add_edge("tools", "agent")
        graph.add_edge("recover", "agent")
        # `finish` nem sempre termina: quando a verificação de números reprova a
        # resposta, ela volta ao modelo com o pedido de correção.
        graph.add_conditional_edges(
            "finish",
            lambda state: END if state.get("final") is not None else "agent",
            {"agent": "agent", END: END},
        )
        return graph.compile()

    # -- execução ----------------------------------------------------------

    def run(self, question: str) -> AgentResult:
        """Responde uma pergunta, devolvendo a resposta e o trace da execução."""
        initial: AgentState = {
            "question": question,
            "messages": [
                SystemMessage(content=self._system_prompt),
                HumanMessage(content=question),
            ],
            "turns": 0,
            "trace": [],
            "final": None,
            "result_numbers": [],
        }

        # Segunda trava contra loop, independente da cota de turnos: cada turno
        # gasta duas transições (agent + tools), mais a entrada e o finish.
        recursion_limit = self._settings.max_agent_turns * 2 + 2

        try:
            state = self._graph.invoke(initial, config={"recursion_limit": recursion_limit})
        except GraphRecursionError as exc:
            raise AgentLoopError("The agent exceeded its execution budget.") from exc

        final: FinalAnswer | None = state.get("final")
        if final is None:
            raise AgentLoopError("The agent finished without producing an answer.")

        trace = list(state.get("trace", []))
        result = AgentResult(
            answer=final.answer,
            assumptions=final.assumptions,
            warnings=final.warnings,
            trace=trace,
            turns=int(state.get("turns", 0)),
            data_queried=any(
                entry.name == "query_sales_data" and entry.status == "ok" for entry in trace
            ),
        )
        logger.info(
            "agent run finished",
            extra={
                "turns": result.turns,
                "tool_calls": len(result.trace),
                "data_queried": result.data_queried,
                "assumptions": len(result.assumptions),
                "warnings": len(result.warnings),
            },
        )
        return result


def _text_of(message: AIMessage) -> str:
    """Extrai texto de um AIMessage, que pode vir como string ou como blocos."""
    content = message.content
    if isinstance(content, str):
        return content
    parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts)
