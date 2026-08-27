"""Fase 3: nada que o modelo escreva sai de uma leitura da tabela `sales`."""

import pytest

from app.analytics.sql_guard import validate_sql
from app.errors import SQLValidationError

MAX_ROWS = 100


def guard(sql: str) -> str:
    return validate_sql(sql, max_rows=MAX_ROWS)


def assert_blocked(sql: str, expected_fragment: str) -> None:
    with pytest.raises(SQLValidationError) as exc_info:
        guard(sql)
    # A mensagem volta para o modelo no self-correction; precisa dizer o que houve.
    assert expected_fragment.lower() in str(exc_info.value).lower()


# --- permitido ----------------------------------------------------------------


def test_simple_select_is_allowed():
    assert "sales" in guard("SELECT * FROM sales LIMIT 10")


def test_aggregate_with_alias_is_allowed():
    sql = guard("SELECT s.local, SUM(s.actual_quantity) AS total FROM sales s GROUP BY s.local")

    assert "SUM" in sql.upper()


def test_cte_is_allowed():
    sql = guard("WITH t AS (SELECT * FROM sales) SELECT COUNT(*) FROM t")

    assert "WITH" in sql.upper()


def test_union_is_allowed():
    sql = guard(
        "SELECT local FROM sales WHERE local = 'Whse_J' "
        "UNION SELECT local FROM sales WHERE local = 'Whse_C'"
    )

    assert "UNION" in sql.upper()


# --- LIMIT --------------------------------------------------------------------


def test_limit_is_injected_when_absent():
    assert guard("SELECT product_id FROM sales").upper().endswith(f"LIMIT {MAX_ROWS}")


def test_smaller_limit_is_preserved():
    assert guard("SELECT product_id FROM sales LIMIT 5").upper().endswith("LIMIT 5")


def test_larger_limit_is_clamped():
    """Um LIMIT alto demais é tão ruim quanto nenhum: não cabe no contexto."""
    assert guard("SELECT * FROM sales LIMIT 500000").upper().endswith(f"LIMIT {MAX_ROWS}")


# --- escrita e comandos -------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "fragment"),
    [
        ("DROP TABLE sales", "drop"),
        ("DELETE FROM sales", "delete"),
        ("INSERT INTO sales VALUES (1)", "insert"),
        ("UPDATE sales SET actual_quantity = 0", "update"),
        ("CREATE TABLE x AS SELECT * FROM sales", "create"),
        ("ALTER TABLE sales RENAME TO other", "alter"),
        ("ATTACH 'other.db'", "attach"),
        ("PRAGMA database_list", "pragma"),
        ("INSTALL httpfs", "install"),
        ("COPY sales TO '/tmp/leak.csv'", "copy"),
        ("SET memory_limit = '1GB'", "set"),
    ],
)
def test_write_and_command_statements_are_blocked(sql, fragment):
    assert_blocked(sql, fragment)


def test_multi_statement_is_blocked():
    assert_blocked("SELECT * FROM sales; DROP TABLE sales;", "one statement")


# --- leitura de arquivo -------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv_auto('C:/Windows/win.ini')",
        "SELECT * FROM read_parquet('/etc/shadow')",
        "SELECT * FROM glob('C:/**')",
        "SELECT * FROM read_text('/etc/passwd')",
        "SELECT (SELECT COUNT(*) FROM read_csv_auto('/etc/passwd')) AS leaked",
    ],
)
def test_file_reading_functions_are_blocked(sql):
    """A raiz destas queries é um SELECT legítimo.

    Bloquear apenas por tipo de statement deixaria passar leitura arbitrária do
    disco: o alvo não é uma tabela nomeada, é uma função de tabela.
    """
    with pytest.raises(SQLValidationError):
        guard(sql)


def test_unknown_table_is_blocked():
    assert_blocked("SELECT * FROM outra_tabela", "not accessible")


def test_information_schema_is_blocked():
    assert_blocked("SELECT * FROM duckdb_settings()", "not")


# --- SQL inválido -------------------------------------------------------------


def test_invalid_sql_is_rejected():
    assert_blocked("SELEC * FROM sales", "not valid sql")


def test_empty_sql_is_rejected():
    assert_blocked("   ", "empty")


# --- evasão por formatação ----------------------------------------------------


def test_comment_does_not_hide_a_second_statement():
    assert_blocked("SELECT * FROM sales; -- comentario\nDROP TABLE sales;", "one statement")


def test_case_and_whitespace_do_not_evade():
    assert_blocked("  dRoP   TaBlE   sales  ", "drop")
