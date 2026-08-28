"""Fase 4: as três ferramentas do agente, sem rede e sem modelo."""

import pytest
from pydantic import ValidationError

from app.agent.model import build_model
from app.agent.tools import normalize_text_list
from app.config import Settings
from app.errors import LLMNotConfiguredError, SQLValidationError

# --- query_sales_data ---------------------------------------------------------


def test_query_returns_rows(tools):
    payload = tools["query_sales_data"].invoke(
        {"sql": "SELECT SUM(actual_quantity) AS total FROM sales"}
    )

    assert payload["row_count"] == 1
    assert payload["rows"][0]["total"] > 0


def test_query_payload_exposes_the_executed_sql(tools):
    """O SQL vai para o trace da resposta: é o que torna a resposta auditável."""
    payload = tools["query_sales_data"].invoke({"sql": "SELECT product_id FROM sales"})

    assert "LIMIT 50" in payload["sql"].upper()


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "DELETE FROM sales",
        "SELECT * FROM sales; DROP TABLE sales;",
        "SELECT * FROM read_csv_auto('C:/Windows/win.ini')",
        "SELECT * FROM outra_tabela",
    ],
)
def test_dangerous_sql_never_reaches_the_database(tools, sql):
    with pytest.raises(SQLValidationError):
        tools["query_sales_data"].invoke({"sql": sql})


# --- inspect_column -----------------------------------------------------------


def test_inspect_column_reveals_the_promotion_trap(tools):
    """Esta é a razão de a ferramenta existir.

    O modelo tende a escrever `WHERE promotion_type IS NOT NULL` para filtrar
    promoções. O valor real de ausência é a string 'None', então esse filtro
    devolveria o dataset inteiro. Inspecionar antes mostra os valores de verdade.
    """
    result = tools["inspect_column"].invoke({"column": "promotion_type"})

    values = {row["value"] for row in result["most_common_values"]}
    assert values == {"None", "Flash"}
    assert result["null_count"] == 0


def test_inspect_column_reports_type_and_cardinality(tools):
    result = tools["inspect_column"].invoke({"column": "local"})

    assert result["dtype"] == "VARCHAR"
    assert result["distinct_count"] >= 1


def test_inspect_unknown_column_lists_the_real_ones(tools):
    """A mensagem volta para o modelo; precisa conter os nomes certos."""
    with pytest.raises(SQLValidationError) as exc_info:
        tools["inspect_column"].invoke({"column": "product"})

    message = str(exc_info.value)
    assert "product_id" in message
    assert "local" in message


# --- submit_answer ------------------------------------------------------------


def test_normalize_keeps_a_valid_list_of_strings():
    assert normalize_text_list(["primeira", "segunda"]) == ["primeira", "segunda"]


def test_normalize_wraps_a_plain_string_in_a_single_item():
    """Sem isto, `list("texto")` devolveria uma lista de caracteres."""
    result = normalize_text_list("interpretei como quantidade")

    assert result == ["interpretei como quantidade"]
    assert len(result) == 1


def test_normalize_parses_a_json_string_holding_a_list():
    assert normalize_text_list('["quantidade", "faturamento"]') == ["quantidade", "faturamento"]


def test_normalize_uses_dict_values_never_keys():
    """O modelo inventa nomes de campo; o conteúdo está nos valores."""
    result = normalize_text_list({"assumption": "usei actual_quantity", "alt": "faturamento"})

    assert result == ["usei actual_quantity", "faturamento"]
    assert "assumption" not in result
    assert "alt" not in result


def test_normalize_parses_a_json_object_and_keeps_the_values():
    result = normalize_text_list('{"answer": "metrica X", "alternatives": ["metrica Y"]}')

    assert result == ["metrica X", "metrica Y"]


@pytest.mark.parametrize("value", [None, "", "   ", [], {}, ["", "  "]])
def test_normalize_discards_empty_values(value):
    assert normalize_text_list(value) == []


def test_normalize_never_produces_a_character_list():
    """Regressão do defeito observado com qwen3.5:4b em execução real."""
    corrupted = '{"answer": "A metrica utilizada foi SUM(actual_quantity)."}'

    result = normalize_text_list(corrupted)

    assert all(len(item) > 1 for item in result)
    assert result == ["A metrica utilizada foi SUM(actual_quantity)."]


def test_submit_answer_rejects_malformed_arguments_at_the_schema(tools):
    """O LangChain valida contra o schema Pydantic antes de executar o corpo.

    Por isso a normalização precisa existir também no `_finish_node`: é ele que lê
    os `tool_calls` crus, sem passar por esta validação — e foi ali que a corrupção
    apareceu na execução real. Ver `tests/test_agent.py`.
    """
    with pytest.raises(ValidationError):
        tools["submit_answer"].invoke(
            {"answer": "resposta", "assumptions": "uma premissa em string"}
        )


def test_submit_answer_returns_structured_payload(tools):
    payload = tools["submit_answer"].invoke(
        {
            "answer": "Product_1359 vendeu mais.",
            "assumptions": ["'mais vendido' interpretado como soma de actual_quantity"],
            "warnings": [],
        }
    )

    assert payload == {
        "answer": "Product_1359 vendeu mais.",
        "assumptions": ["'mais vendido' interpretado como soma de actual_quantity"],
        "warnings": [],
    }


def test_submit_answer_defaults_to_empty_lists(tools):
    payload = tools["submit_answer"].invoke({"answer": "Resposta simples."})

    assert payload["assumptions"] == []
    assert payload["warnings"] == []


# --- binding ------------------------------------------------------------------


def test_all_three_tools_are_exposed(tools):
    assert set(tools) == {"query_sales_data", "inspect_column", "submit_answer"}


def test_tools_carry_descriptions_for_the_model(tools):
    """A docstring é o que o modelo lê para decidir qual ferramenta usar."""
    for tool in tools.values():
        assert tool.description
        assert len(tool.description) > 40


# --- model factory ------------------------------------------------------------


def test_build_model_fails_clearly_without_a_key():
    with pytest.raises(LLMNotConfiguredError) as exc_info:
        build_model(Settings(_env_file=None))

    assert "OPENAI_API_KEY" in str(exc_info.value)


def test_build_model_returns_a_chat_model_without_touching_the_network():
    model = build_model(Settings(_env_file=None, openai_api_key="sk-fake-key"))

    assert model.temperature == 0
    assert hasattr(model, "bind_tools")


# --- escolha de provider ------------------------------------------------------


def test_openai_is_the_default_provider():
    settings = Settings(_env_file=None)

    assert settings.llm_provider == "openai"
    assert settings.resolved_model == "gpt-4o-mini"
    assert settings.llm_configured is False


def test_ollama_needs_no_credential():
    """Modelo local não usa chave: o /ask fica disponível sem configurar nada."""
    settings = Settings(_env_file=None, llm_provider="ollama")

    assert settings.llm_configured is True
    assert settings.resolved_model == "llama3.1"


def test_explicit_model_overrides_the_provider_default():
    settings = Settings(_env_file=None, llm_provider="ollama", llm_model="qwen2.5")

    assert settings.resolved_model == "qwen2.5"


def test_build_model_returns_ollama_without_touching_the_server():
    """Construir o client não conecta; a indisponibilidade aparece na 1a chamada."""
    model = build_model(Settings(_env_file=None, llm_provider="ollama"))

    assert type(model).__name__ == "ChatOllama"
    assert hasattr(model, "bind_tools")


def test_openai_error_message_points_to_the_local_alternative():
    with pytest.raises(LLMNotConfiguredError) as exc_info:
        build_model(Settings(_env_file=None, llm_provider="openai"))

    assert "LLM_PROVIDER=ollama" in str(exc_info.value)


def test_unknown_provider_is_rejected_by_configuration():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider="gpt5-turbo-imaginario")
