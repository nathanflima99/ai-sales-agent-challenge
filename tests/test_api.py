"""Fase 6: contrato HTTP, com o agente mockado — sem rede."""

import pytest
from fastapi.testclient import TestClient

from app.agent.graph import AgentResult
from app.agent.state import ToolTrace
from app.errors import AgentLoopError, LLMError
from app.main import create_app


@pytest.fixture
def answering_client(client):
    """Cliente com um agente falso instalado no `app.state`."""

    class StubAgent:
        def __init__(self) -> None:
            self.questions: list[str] = []

        def run(self, question: str) -> AgentResult:
            self.questions.append(question)
            return AgentResult(
                answer="Product_1359 foi o mais vendido.",
                assumptions=["'mais vendido' = SUM(actual_quantity)"],
                warnings=["Duplicatas exatas existem no dataset."],
                trace=[
                    ToolTrace(
                        name="query_sales_data",
                        args={"sql": "SELECT product_id FROM sales"},
                        status="ok",
                        elapsed_ms=12.3,
                        sql="SELECT product_id FROM sales LIMIT 100",
                        row_count=1,
                        cache_hit=False,
                    )
                ],
                turns=2,
            )

    client.app.state.agent = StubAgent()
    return client


# --- health -------------------------------------------------------------------


def test_health_is_independent_from_the_llm(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "llm": "unconfigured",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "dataset_rows": 25,
    }


def test_every_response_carries_a_request_id(client):
    response = client.get("/health")

    assert response.headers["X-Request-ID"]


def test_request_id_from_the_client_is_preserved(client):
    response = client.get("/health", headers={"X-Request-ID": "abc123"})

    assert response.headers["X-Request-ID"] == "abc123"


# --- ask: caminho feliz -------------------------------------------------------


def test_ask_returns_answer_assumptions_warnings_and_trace(answering_client):
    response = answering_client.post("/ask", json={"question": "Qual produto foi mais vendido?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Product_1359 foi o mais vendido."
    assert body["assumptions"] == ["'mais vendido' = SUM(actual_quantity)"]
    assert body["warnings"] == ["Duplicatas exatas existem no dataset."]


def test_trace_exposes_the_executed_sql(answering_client):
    """O trace é o que permite reconferir qualquer número à mão."""
    response = answering_client.post("/ask", json={"question": "Qual produto?"})
    trace = response.json()["metadata"]["trace"]

    assert trace[0]["sql"] == "SELECT product_id FROM sales LIMIT 100"
    assert trace[0]["status"] == "ok"


def test_metadata_reports_turns_and_duration(answering_client):
    metadata = answering_client.post("/ask", json={"question": "Q"}).json()["metadata"]

    assert metadata["turns"] == 2
    assert metadata["total_ms"] >= 0
    assert metadata["request_id"]


# --- ask: validação -----------------------------------------------------------


@pytest.mark.parametrize("payload", [{"question": ""}, {}, {"question": "x" * 1001}])
def test_invalid_questions_are_rejected_before_the_agent(answering_client, payload):
    response = answering_client.post("/ask", json=payload)

    assert response.status_code == 422
    assert answering_client.app.state.agent.questions == []


# --- ask: falhas --------------------------------------------------------------


def test_ask_without_api_key_returns_an_actionable_503(client):
    """Sem chave a aplicação sobe; só o /ask recusa, dizendo como configurar."""
    response = client.post("/ask", json={"question": "Qual produto foi mais vendido?"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "llm_not_configured"
    assert "OPENAI_API_KEY" in body["error"]["message"]


def test_llm_failure_returns_503_without_a_stack_trace(client):
    class FailingAgent:
        def run(self, question: str) -> AgentResult:
            raise LLMError("upstream connection to provider-host-1 refused")

    client.app.state.agent = FailingAgent()
    response = client.post("/ask", json={"question": "Q"})

    assert response.status_code == 503
    assert "Traceback" not in response.text
    assert "provider-host-1" not in response.text


def test_agent_loop_failure_returns_500_without_internal_detail(client):
    class LoopingAgent:
        def run(self, question: str) -> AgentResult:
            raise AgentLoopError("did not converge at /srv/app/agent/graph.py")

    client.app.state.agent = LoopingAgent()
    response = client.post("/ask", json={"question": "Q"})

    assert response.status_code == 500
    assert response.json()["error"]["message"] == "Internal server error"
    assert "/srv/app" not in response.text


# --- UI -----------------------------------------------------------------------


def test_ui_is_served_at_the_root(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "AI Sales Agent" in response.text


def test_openapi_documents_the_ask_contract():
    with TestClient(create_app()) as client:
        schema = client.get("/openapi.json").json()

    assert "/ask" in schema["paths"]
    assert "/health" in schema["paths"]
