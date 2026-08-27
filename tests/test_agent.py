"""Fase 5: o grafo do agente, com modelo falso — sem rede e sem tokens."""

import pytest
from langchain_core.messages import AIMessage

from app.agent.graph import SalesAgent
from app.agent.prompts import build_system_prompt
from app.agent.tools import build_tools
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
                {"answer": "O total realizado foi 8181.", "assumptions": [], "warnings": []},
                call_id="call_2",
            ),
        ]
    )

    result = agent.run("Qual foi a quantidade total realizada?")

    assert result.answer == "O total realizado foi 8181."
    assert result.turns == 2
    assert [t.name for t in result.trace] == ["query_sales_data", "submit_answer"]
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
    assert [t.status for t in result.trace] == ["error", "ok", "ok"]
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
    assert result.trace[-1].status == "error"
    assert "without calling submit_answer" in (result.trace[-1].error or "")


def test_provider_failure_becomes_a_domain_error(sample_repository):
    profile = build_profile(sample_repository.connection)
    settings = Settings(_env_file=None)
    tools = build_tools(sample_repository, profile, settings)
    agent = SalesAgent(ExplodingChatModel(), tools, profile, settings)

    with pytest.raises(LLMError):
        agent.run("Pergunta")


# --- prompt -------------------------------------------------------------------


def test_system_prompt_warns_about_the_dataset_traps(sample_repository):
    prompt = build_system_prompt(build_profile(sample_repository.connection))

    assert "product_id" in prompt
    assert "'None'" in prompt
    assert "IS NOT NULL" in prompt
    assert "submit_answer" in prompt
    assert "assumptions" in prompt


def test_system_prompt_does_not_leak_ground_truth_answers(sample_repository):
    """O perfil vai para o prompt, mas as respostas não.

    Se o prompt contivesse os agregados, o modelo poderia respondê-los sem
    consultar, e a regra de nunca calcular de cabeça viraria letra morta.
    """
    prompt = build_system_prompt(build_profile(sample_repository.connection))

    assert "Product_1359" not in prompt
    assert "953" not in prompt
