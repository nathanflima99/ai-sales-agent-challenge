"""Validação do SQL gerado pelo modelo, por AST.

Validar por string é frágil: comentários, maiúsculas, aliases e statements
encadeadas escapam de qualquer regex. Aqui o SQL é parseado e julgado pelo **tipo
dos nós** da árvore, que é o que ele realmente é, não pelo que ele parece.

O guard é a única fronteira entre um texto produzido por um LLM e o motor de
consulta. Ele assume que o texto é hostil.
"""

import logging
from typing import cast

import sqlglot
from sqlglot import exp

from app.errors import SQLValidationError

logger = logging.getLogger(__name__)

DIALECT = "duckdb"

#: Única tabela que o agente enxerga.
ALLOWED_TABLES = frozenset({"sales"})

#: Tipos de nó que jamais aparecem numa leitura. A checagem de raiz já barra a
#: maioria, mas a varredura completa cobre um nó aninhado que a raiz não revele.
_FORBIDDEN_NODE_NAMES = (
    "Alter",
    "Attach",
    "Command",
    "Copy",
    "Create",
    "Delete",
    "Detach",
    "Drop",
    "Export",
    "Insert",
    "Install",
    "LoadData",
    "Merge",
    "Pragma",
    "Set",
    "TruncateTable",
    "Update",
    "Use",
)
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    node
    for node in (getattr(exp, name, None) for name in _FORBIDDEN_NODE_NAMES)
    if isinstance(node, type) and issubclass(node, exp.Expression)
)

#: Funções do DuckDB que leem do sistema de arquivos ou da rede. Sem isto,
#: `SELECT * FROM read_csv_auto('C:/Windows/win.ini')` passaria: a raiz é um
#: Select legítimo e o alvo não é uma tabela nomeada, é uma função de tabela.
FORBIDDEN_FUNCTIONS = frozenset(
    {
        "csv_scan",
        "delta_scan",
        "glob",
        "iceberg_scan",
        "parquet_scan",
        "read_blob",
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_ndjson",
        "read_ndjson_auto",
        "read_ndjson_objects",
        "read_parquet",
        "read_text",
        "read_xlsx",
        "sniff_csv",
    }
)

#: Raízes aceitas. `WITH ... SELECT` chega como Select com a cláusula anexada.
ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.Union)


def validate_sql(sql: str, max_rows: int) -> str:
    """Valida e normaliza o SQL, devolvendo a versão segura para execução.

    As mensagens de erro são escritas para serem lidas **pelo modelo**: elas voltam
    como `ToolMessage` no self-correction da Fase 5, e uma mensagem vaga custa um
    turno inteiro de tentativa e erro.

    Raises:
        SQLValidationError: se o SQL for inválido ou fizer algo além de ler `sales`.
    """
    if not sql or not sql.strip():
        raise SQLValidationError("The query is empty.")

    try:
        statements = sqlglot.parse(sql, dialect=DIALECT)
    except sqlglot.ParseError as exc:
        raise SQLValidationError(f"The query is not valid SQL: {exc}") from exc

    statements = [statement for statement in statements if statement is not None]
    if not statements:
        raise SQLValidationError("The query is empty.")
    if len(statements) > 1:
        raise SQLValidationError(
            "Only one statement is allowed; remove everything after the first ';'."
        )

    statement = statements[0]

    if not isinstance(statement, (exp.Select, exp.Union)):
        raise SQLValidationError(
            f"Only SELECT statements are allowed, got {type(statement).__name__.upper()}."
        )

    _reject_forbidden_nodes(statement)
    _reject_forbidden_functions(statement)
    _reject_unknown_tables(statement)

    guarded = _apply_row_limit(statement, max_rows)
    normalized = guarded.sql(dialect=DIALECT)

    logger.info("sql validated", extra={"sql": normalized})
    return normalized


def _reject_forbidden_nodes(statement: exp.Expression) -> None:
    for node in statement.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise SQLValidationError(
                f"{type(node).__name__.upper()} is not allowed; the dataset is read-only."
            )


def _reject_forbidden_functions(statement: exp.Expression) -> None:
    for function in statement.find_all(exp.Anonymous):
        name = function.name.lower()
        if name in FORBIDDEN_FUNCTIONS:
            raise SQLValidationError(
                f"The function '{name}' is not available; only the 'sales' table can be read."
            )


def _reject_unknown_tables(statement: exp.Expression) -> None:
    """Garante que toda referência de tabela é `sales` ou um CTE local.

    Segunda linha de defesa: mesmo que uma função de leitura escape da lista acima,
    ela aparece na árvore como uma tabela sem nome e é barrada aqui.
    """
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    allowed = ALLOWED_TABLES | cte_names

    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if not name:
            raise SQLValidationError(
                "Table functions are not allowed; query the 'sales' table directly."
            )
        if name not in allowed:
            raise SQLValidationError(
                f"Table '{table.name}' is not accessible; only 'sales' is available."
            )


def _apply_row_limit(statement: exp.Query, max_rows: int) -> exp.Query:
    """Injeta ou reduz o LIMIT.

    Um LIMIT alto demais é tão problemático quanto nenhum: 200 mil linhas cabem na
    resposta da tool mas não no contexto do modelo.
    """
    current = statement.args.get("limit")
    if current is None:
        return cast(exp.Query, statement.limit(max_rows))

    try:
        requested = int(current.expression.name)
    except (AttributeError, ValueError):
        return cast(exp.Query, statement.limit(max_rows))

    if requested > max_rows:
        return cast(exp.Query, statement.limit(max_rows))
    return statement
