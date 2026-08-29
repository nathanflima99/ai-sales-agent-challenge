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
from app.agent.verification import (
    correction_message,
    numbers_in_payload,
    unverified_numbers,
)
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

    #: Falso quando algum número apresentado ao usuário não foi encontrado em
    #: nenhum resultado de consulta e a cota de turnos acabou antes da correção.
    numbers_verified: bool = True


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
        # O perfil do dataset é resultado de consulta: `build_profile` roda SQL
        # contra a mesma view no startup. Semear a evidência com ele é literal —
        # quando o modelo cita as 203.635 linhas, esse número veio mesmo do
        # banco, só que numa consulta anterior à pergunta.
        #
        # Isto é diferente de isentar contexto da verificação: aqui não há
        # exceção, há evidência. `numbers_verified` continua significando "todo
        # número citado saiu de uma consulta".
        self._profile_numbers = _profile_evidence(profile)
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
                    verified = self._verify(state, final, args, call.get("id"))
                    verified["trace"] = [
                        ToolTrace(name=SUBMIT_ANSWER, args=args, status="ok"),
                        *verified.get("trace", []),
                    ]
                    return verified

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

        # A prosa também passa pela verificação. Sem isso, bastaria o modelo
        # responder sem chamar a ferramenta — caminho observado em ~30% das
        # execuções — para publicar qualquer número sem rastreabilidade.
        fallback = FinalAnswer(answer=text, assumptions=[], warnings=[FALLBACK_WARNING])
        verified = self._verify(state, fallback, None, None)
        verified["trace"] = [
            ToolTrace(
                name=SUBMIT_ANSWER,
                status="error",
                error="Model answered without calling submit_answer.",
            ),
            *verified.get("trace", []),
        ]
        return verified

    def _verify(
        self,
        state: AgentState,
        final: FinalAnswer,
        args: dict[str, Any] | None,
        call_id: str | None,
    ) -> dict[str, Any]:
        """Confere que todo número apresentado ao usuário veio de uma consulta.

        Esta é a trava que faltava. A regra "o DuckDB calcula" vivia apenas no
        prompt, e instrução é seguida de forma probabilística: perguntado pela
        diferença entre planejado e realizado, o modelo consultou as duas somas e
        subtraiu na resposta, errando o valor em 10.000 e o sinal.

        Verifica `answer`, `assumptions` e `warnings`: os três aparecem na
        resposta da API, e um número inventado numa premissa engana tanto quanto
        um inventado na resposta.

        Quando um número não é rastreável, ele volta ao modelo no mesmo mecanismo
        que trata SQL rejeitado. A cota de turnos limita as tentativas.

        Esgotada a cota, a resposta é entregue com aviso explícito e
        `numbers_verified=False` no metadata. Devolver 500 daria nada a quem
        perguntou; o campo permite ao cliente decidir sem interpretar prosa.
        """
        claims = "\n".join([final.answer, *final.assumptions, *final.warnings])
        unverified = unverified_numbers(claims, state["question"], set(state["result_numbers"]))

        if not unverified:
            # Uma entrada `ok` explícita registra que a verificação rodou. Sem
            # ela, "sem erro no trace" seria ambíguo entre verificado e ignorado.
            return {
                "final": final,
                "numbers_verified": True,
                "trace": [ToolTrace(name="number_check", args=args or {}, status="ok")],
            }

        trace = ToolTrace(
            name="number_check",
            status="error",
            error=f"Numbers not found in any query result: {', '.join(unverified)}",
        )

        # Uma tentativa, não a cota inteira. Medido com qwen3.5:4b: o mesmo
        # número foi reprovado nos turnos 2, 4 e 5 da mesma execução — o modelo
        # foi avisado três vezes e não corrigiu. Insistir triplicava a latência
        # sem mudar a resposta. A trava vale como detector; a correção, quando
        # acontece, acontece na primeira tentativa.
        already_retried = any(entry.name == "number_check" for entry in state["trace"])

        if not already_retried and state["turns"] < self._settings.max_agent_turns:
            logger.warning(
                "answer cites numbers no query returned, asking for a correction",
                extra={"unverified": unverified, "turns": state["turns"]},
            )
            # Precisa ser ToolMessage quando veio de `submit_answer`: a OpenAI
            # rejeita a próxima chamada se um tool call ficar sem resposta com o
            # id correspondente. Um HumanMessage aqui quebraria o provider.
            correction = correction_message(unverified)
            reply: BaseMessage = (
                ToolMessage(content=correction, tool_call_id=call_id, status="error")
                if call_id
                else HumanMessage(content=correction)
            )
            return {"messages": [reply], "trace": [trace]}

        logger.warning(
            "answer cites unverified numbers and the turn budget is over",
            extra={"unverified": unverified},
        )
        final.warnings.append(
            "Alguns números desta resposta não foram encontrados em nenhum "
            f"resultado de consulta ({', '.join(unverified)}) e podem ter sido "
            "calculados pelo modelo."
        )
        return {"final": final, "numbers_verified": False, "trace": [trace]}

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
            # O perfil já é resultado de consulta; ver `_profile_evidence`.
            "result_numbers": list(self._profile_numbers),
            "numbers_verified": True,
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
            numbers_verified=bool(state.get("numbers_verified", True)),
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


def _profile_evidence(profile: DatasetProfile) -> set[str]:
    """Números do perfil do dataset, que são resultado de consulta.

    `build_profile` roda SQL contra a mesma view no startup, então estes valores
    têm a mesma procedência de qualquer outro do trace — só foram obtidos antes
    da pergunta. Sem isto, citar as 203.635 linhas informadas no próprio prompt
    seria tratado como número inventado: aconteceu duas vezes numa medição de 32
    execuções, gastando um turno cada.
    """
    facts: list[object] = [
        profile.row_count,
        profile.product_count,
        len(profile.locations),
        *profile.promotion_types.values(),
        *profile.null_counts.values(),
    ]
    return numbers_in_payload(facts)


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
