"""Validação de schema e perfil estático do dataset.

O perfil é calculado uma vez no startup e injetado no system prompt do agente
(Fase 5). Ele não é uma ferramenta: é informação constante durante a execução, e
gastar uma chamada de tool para devolver texto fixo seria desperdício de latência
e de tokens.
"""

import logging
from datetime import date

import duckdb
from pydantic import BaseModel

from app.errors import DatasetError

logger = logging.getLogger(__name__)

# Nomes reais conferidos no CSV do desafio. Atenção: `product_id` e `local`,
# não `product` e `location`.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "product_id",
    "local",
    "date",
    "planned_quantity",
    "actual_quantity",
    "planned_price",
    "promotion_type",
    "actual_price",
    "service_level",
)


class DatasetProfile(BaseModel):
    """Retrato estático do dataset, calculado no startup."""

    row_count: int
    columns: list[str]
    column_types: dict[str, str]
    date_min: date
    date_max: date
    product_count: int
    locations: list[str]
    promotion_types: dict[str, int]
    null_counts: dict[str, int]
    constant_columns: list[str]

    @property
    def has_nulls(self) -> bool:
        return any(count > 0 for count in self.null_counts.values())


def validate_schema(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Confere que a view `sales` expõe todas as colunas obrigatórias.

    Falha no startup, não na primeira pergunta: um dataset incompatível é erro de
    operação, e descobrir isso durante um request esconde a causa real.
    """
    described = connection.execute("DESCRIBE sales").fetchall()
    column_types = {str(row[0]): str(row[1]) for row in described}

    missing = [column for column in REQUIRED_COLUMNS if column not in column_types]
    if missing:
        raise DatasetError(
            f"Dataset is missing required column(s): {', '.join(missing)}. "
            f"Found: {', '.join(column_types)}"
        )

    return column_types


def build_profile(connection: duckdb.DuckDBPyConnection) -> DatasetProfile:
    """Calcula o perfil do dataset inteiramente em SQL."""
    column_types = validate_schema(connection)
    columns = list(column_types)

    row_count, product_count, date_min, date_max = connection.execute(
        """
        SELECT COUNT(*), COUNT(DISTINCT product_id), MIN(date), MAX(date)
        FROM sales
        """
    ).fetchone() or (0, 0, None, None)

    locations = [
        str(row[0])
        for row in connection.execute("SELECT DISTINCT local FROM sales ORDER BY local").fetchall()
    ]

    promotion_types = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT promotion_type, COUNT(*) FROM sales GROUP BY 1 ORDER BY 2 DESC"
        ).fetchall()
    }

    null_counts: dict[str, int] = {}
    constant_columns: list[str] = []
    # Os nomes vêm do DESCRIBE da própria view, nunca de entrada de usuário, e são
    # interpolados entre aspas duplas. Não há caminho por onde texto externo chegue
    # aqui — o SQL do modelo passa pelo guard e pelo repositório, não por este loop.
    for column in columns:
        nulls, distinct = connection.execute(
            f'SELECT COUNT(*) - COUNT("{column}"), COUNT(DISTINCT "{column}") FROM sales'
        ).fetchone() or (0, 0)
        null_counts[column] = int(nulls)
        if int(distinct) == 1:
            constant_columns.append(column)

    profile = DatasetProfile(
        row_count=int(row_count),
        columns=columns,
        column_types=column_types,
        date_min=date_min,
        date_max=date_max,
        product_count=int(product_count),
        locations=locations,
        promotion_types=promotion_types,
        null_counts=null_counts,
        constant_columns=constant_columns,
    )

    logger.info(
        "dataset profiled",
        extra={
            "row_count": profile.row_count,
            "product_count": profile.product_count,
            "locations": len(profile.locations),
            "constant_columns": profile.constant_columns,
        },
    )
    return profile
