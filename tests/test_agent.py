"""Fase 5: o grafo do agente, com modelo falso — sem rede e sem tokens."""

import pytest
from langchain_core.messages import AIMessage

from app.agent.graph import EMPTY_RESPONSE_NUDGE, FALLBACK_WARNING, SalesAgent
from app.agent.prompts import build_system_prompt
from app.agent.tools import SUBMIT_ANSWER, build_tools
from app.analytics.profiling import build_profile
from app.config import Settings
from app.errors import AgentLoopError, LLMError
from tests.fakes import ExplodingChatModel, ScriptedChatModel, tool_call

TOTAL_SQL = "SELECT SUM(actual_quantity) AS total FROM sales"


@pytest.fixture
def make_agent(sample_repository):
    """Constrói um agente sobre a amostra, com respostas do modelo programadas."""

    def _build(responses, max_turns: int = 6) -> SalesAgent:
        profile = build_profile(sample_repository.connection)
        settings = Settings(_env_file=None, max_agent_turns=max_turns, max_query_rows=50)
        tools = build_tools(sample_repository, profile, settings)
        model = ScriptedChatModel(responses=list(responses))
        return SalesAgent(model, tools, profile, settings)

    return _build


# --- fluxo feliz --------------------------------------------------------------


def test_single_query_then_answer(make_agent):
    agent = make_agent(
        [
            tool_call("query_sales_data", {"sql": TOTAL_SQL}),
            tool_call(
                "submit_answer",
                {"answer": "O total realizado foi 33978.", "assumptions": [], "warnings": []},
                call_id="call_2",
            ),
        ]
    )

    result = agent.run("Qual foi a quantidade total realizada?")

    assert result.answer == "O total realizado foi 33978."
    assert result.turns == 2
    assert [t.name for t in result.trace] == ["query_sales_data", "submit_answer", "number_check"]
    assert result.trace[0].status == "ok"
    # O SQL executado fica visível no trace: é o que torna a resposta auditável.
    assert "SUM(ACTUAL_QUANTITY)" in (result.trace[0].sql or "").upper()
    assert "LIMIT 50" in (result.trace[0].sql or "").upper()


def test_assumptions_and_warnings_reach_the_result(make_agent):
    agent = make_agent(
        [
            tool_call(
                "submit_answer",
                {
                    "answer": "Interpretei como quantidade.",
                    "assumptions": ["'total de vendas' lido como SUM(actual_quantity)"],
                    "warnings": ["Faturamento daria outra ordem de grandeza."],
                },
            )
        ]
    )

    result = agent.run("Qual foi o total de vendas?")

    assert result.assumptions == ["'total de vendas' lido como SUM(actual_quantity)"]
    assert result.warnings == ["Faturamento daria outra ordem de grandeza."]


# --- self-correction ----------------------------------------------------------


def test_agent_recovers_from_a_rejected_query(make_agent):
    """O erro da ferramenta volta para o modelo, não para o usuário.

    É isto que torna o sistema um agente: ele observa o resultado da própria ação,
    detecta a falha e replaneja.
    """
    agent = make_agent(
        [
            tool_call("query_sales_data", {"sql": "DROP TABLE sales"}),
            tool_call("query_sales_data", {"sql": TOTAL_SQL}, call_id="call_2"),
            tool_call("submit_answer", {"answer": "Consegui na segunda tentativa."}, "call_3"),
        ]
    )

    result = agent.run("Qual o total?")

    assert result.answer == "Consegui na segunda tentativa."
    assert [t.status for t in result.trace] == ["error", "ok", "ok", "ok"]
    assert "DROP" in (result.trace[0].error or "").upper()


def test_error_message_returned_to_the_model_is_actionable(make_agent):
    """A mensagem precisa dizer o que houve, senão o modelo gasta um turno chutando."""
    agent = make_agent(
        [
            tool_call("query_sales_data", {"sql": "SELECT * FROM outra_tabela"}),
            tool_call("submit_answer", {"answer": "ok"}, call_id="call_2"),
        ]
    )

    result = agent.run("Pergunta")
    model_messages = result.trace[0].error or ""

    assert "not accessible" in model_messages
    assert "sales" in model_messages


def test_unknown_tool_is_reported_instead_of_crashing(make_agent):
    agent = make_agent(
        [
            tool_call("ferramenta_inexistente", {}),
            tool_call("submit_answer", {"answer": "segui em frente"}, call_id="call_2"),
        ]
    )

    result = agent.run("Pergunta")

    assert result.trace[0].status == "error"
    assert "Unknown tool" in (result.trace[0].error or "")


# --- travas contra loop -------------------------------------------------------


def test_turn_budget_is_enforced(make_agent):
    """Um modelo teimoso não pode queimar créditos indefinidamente."""
    agent = make_agent(
        [tool_call("query_sales_data", {"sql": TOTAL_SQL}, call_id=f"c{i}") for i in range(10)],
        max_turns=3,
    )

    with pytest.raises(AgentLoopError) as exc_info:
        agent.run("Pergunta que nunca termina")

    assert "3 turns" in str(exc_info.value)


# --- degradação graciosa ------------------------------------------------------


def test_prose_answer_without_submit_answer_is_still_delivered(make_agent):
    """Recusar-se a responder por formalidade seria pior para quem perguntou."""
    agent = make_agent([AIMessage(content="A resposta em prosa, sem chamar a tool.")])

    result = agent.run("Pergunta")

    assert result.answer == "A resposta em prosa, sem chamar a tool."
    assert any(t.name == SUBMIT_ANSWER and t.status == "error" for t in result.trace)
    assert any("without calling submit_answer" in (t.error or "") for t in result.trace)


@pytest.mark.parametrize("content", ["", "   ", "\n\n"])
def test_empty_response_is_retried_and_then_answered(make_agent, content):
    """Resposta vazia é transitória, não terminal.

    Medido com qwen3.5:4b: 6 de 32 execuções vieram sem tool call, sem texto e
    sem raciocínio. Das 26 que responderam, 26 estavam corretas, então tratar o
    vazio como falha descartava ~19% das perguntas por um soluço do modelo.
    """
    agent = make_agent(
        [
            AIMessage(content=content),
            tool_call("submit_answer", {"answer": "Consegui na segunda tentativa."}),
        ]
    )

    result = agent.run("Pergunta")

    assert result.answer == "Consegui na segunda tentativa."
    assert result.trace[0].name == "model_retry"


def test_the_retry_asks_the_model_to_continue(sample_repository):
    """O nudge existe para o contexto mudar.

    Com `temperature=0`, reenviar o mesmo histórico convida a mesma resposta.
    """
    profile = build_profile(sample_repository.connection)
    settings = Settings(_env_file=None, max_agent_turns=6, max_query_rows=50)
    tools = build_tools(sample_repository, profile, settings)
    model = ScriptedChatModel(
        responses=[AIMessage(content=""), tool_call("submit_answer", {"answer": "ok"})]
    )

    SalesAgent(model, tools, profile, settings).run("Pergunta")

    assert any(EMPTY_RESPONSE_NUDGE in str(m.content) for m in model.calls[1])


def test_persistent_empty_responses_still_fail(make_agent):
    """Um modelo que nunca responde precisa falhar, não girar para sempre."""
    agent = make_agent([AIMessage(content="") for _ in range(10)], max_turns=3)

    with pytest.raises(AgentLoopError):
        agent.run("Pergunta")


# --- trava contra o modelo fazer conta ----------------------------------------


def test_answer_with_a_number_no_query_returned_is_sent_back(make_agent):
    """O caso real: consultou as parcelas e subtraiu na resposta.

    A primeira tentativa cita um número que nenhuma consulta devolveu; ele volta
    ao modelo como observação, e a segunda tentativa cita só o que veio do banco.
    """
    agent = make_agent(
        [
            tool_call("query_sales_data", {"sql": TOTAL_SQL}),
            tool_call("submit_answer", {"answer": "A diferença é 4305470."}, "c2"),
            tool_call("submit_answer", {"answer": "O total é 33978."}, "c3"),
        ]
    )

    result = agent.run("Qual a diferença?")

    assert result.answer == "O total é 33978."
    assert any(t.name == "number_check" and t.status == "error" for t in result.trace)


def test_unverified_number_is_flagged_when_the_budget_runs_out(make_agent):
    """Sem turnos para corrigir, a resposta sai marcada em vez de virar erro.

    Uma resposta possivelmente imprecisa, dita como tal, serve melhor a quem
    perguntou do que um 500.
    """
    agent = make_agent(
        [
            tool_call("query_sales_data", {"sql": TOTAL_SQL}),
            tool_call("submit_answer", {"answer": "A diferença é 4305470."}, "c2"),
        ],
        max_turns=2,
    )

    result = agent.run("Qual a diferença?")

    assert "4305470" in result.answer
    assert any("não foram encontrados" in w for w in result.warnings)


def test_provider_failure_becomes_a_domain_error(sample_repository):
    profile = build_profile(sample_repository.connection)
    settings = Settings(_env_file=None)
    tools = build_tools(sample_repository, profile, settings)
    agent = SalesAgent(ExplodingChatModel(), tools, profile, settings)

    with pytest.raises(LLMError):
        agent.run("Pergunta")


# --- data_queried -------------------------------------------------------------


def test_data_queried_is_true_after_a_successful_query(make_agent):
    agent = make_agent(
        [
            tool_call("query_sales_data", {"sql": TOTAL_SQL}),
            tool_call("submit_answer", {"answer": "resposta fundamentada"}, call_id="c2"),
        ]
    )

    assert agent.run("Qual o total?").data_queried is True


def test_data_queried_is_false_without_any_query(make_agent):
    """Recusa legítima: não há o que consultar, e a resposta continua válida."""
    agent = make_agent([tool_call("submit_answer", {"answer": "O dataset cobre apenas 2012."})])

    result = agent.run("Qual a previsao de vendas para 2030?")

    assert result.data_queried is False
    assert result.answer == "O dataset cobre apenas 2012."


def test_data_queried_is_false_when_the_query_failed(make_agent):
    """Uma consulta rejeitada pelo guard não fundamenta nada."""
    agent = make_agent(
        [
            tool_call("query_sales_data", {"sql": "DROP TABLE sales"}),
            tool_call("submit_answer", {"answer": "respondi mesmo assim"}, call_id="c2"),
        ]
    )

    result = agent.run("Pergunta")

    assert result.trace[0].status == "error"
    assert result.data_queried is False


def test_fallback_after_a_successful_query_is_flagged_but_kept(make_agent):
    """Caso observado com qwen3.5:4b: consulta o dataset e responde em prosa."""
    agent = make_agent(
        [
            tool_call("query_sales_data", {"sql": TOTAL_SQL}),
            AIMessage(content="O total realizado foi 33978."),
        ]
    )

    result = agent.run("Qual o total?")

    assert result.data_queried is True
    assert result.answer == "O total realizado foi 33978."
    assert FALLBACK_WARNING in result.warnings
    assert any(t.name == SUBMIT_ANSWER and t.status == "error" for t in result.trace)


def test_malformed_submit_answer_arguments_are_normalized(make_agent):
    """Regressão do defeito observado em execução real com qwen3.5:4b.

    O modelo mandou uma string JSON onde o schema pede lista, e um objeto no lugar
    da outra. O `_finish_node` lê os `tool_calls` crus — sem a validação Pydantic
    que a tool teria — então a normalização precisa acontecer aqui.
    """
    agent = make_agent(
        [
            tool_call(
                "submit_answer",
                {
                    "answer": "Product_1359 foi o mais vendido.",
                    "assumptions": '{"answer": "Usei SUM(actual_quantity)."}',
                    "warnings": {"sample_size": "Amostra promocional pequena."},
                },
            )
        ]
    )

    result = agent.run("Qual produto foi mais vendido?")

    assert result.assumptions == ["Usei SUM(actual_quantity)."]
    assert result.warnings == ["Amostra promocional pequena."]
    # O sintoma antigo: list("texto") virando uma lista de caracteres.
    assert all(len(item) > 1 for item in result.assumptions + result.warnings)


def test_inspect_column_alone_does_not_count_as_querying(make_agent):
    agent = make_agent(
        [
            tool_call("inspect_column", {"column": "local"}),
            tool_call("submit_answer", {"answer": "só inspecionei"}, call_id="c2"),
        ]
    )

    assert agent.run("Pergunta").data_queried is False


# --- prompt -------------------------------------------------------------------


def test_system_prompt_warns_about_the_dataset_traps(sample_repository):
    prompt = build_system_prompt(build_profile(sample_repository.connection))

    assert "product_id" in prompt
    assert "'None'" in prompt
    assert "IS NOT NULL" in prompt
    assert "submit_answer" in prompt
    assert "assumptions" in prompt


def test_system_prompt_pushes_derived_values_into_sql(sample_repository):
    """A regra genérica "use a ferramenta" não bastou na prática.

    Perguntado pela diferença entre planejado e realizado, o modelo consultou as
    duas somas e subtraiu na resposta. A conta era o enunciado da pergunta, e
    mesmo assim não foi para o SQL.
    """
    prompt = build_system_prompt(build_profile(sample_repository.connection))

    assert "DERIVADOS" in prompt
    assert "SUM(actual_quantity) - SUM(planned_quantity)" in prompt


def test_system_prompt_does_not_leak_ground_truth_answers(sample_repository):
    """O perfil vai para o prompt, mas as respostas não.

    Se o prompt contivesse os agregados, o modelo poderia respondê-los sem
    consultar, e a regra de nunca calcular de cabeça viraria letra morta.
    """
    prompt = build_system_prompt(build_profile(sample_repository.connection))

    assert "Product_1359" not in prompt
    assert "953" not in prompt
