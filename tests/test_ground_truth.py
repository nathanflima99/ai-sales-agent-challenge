"""Fase 2: a camada analítica está correta, sem nenhuma IA envolvida.

Estes valores foram conferidos executando SQL diretamente sobre o CSV do desafio.
Se um teste daqui falhar, é o código que está errado — nunca o número.
"""

from datetime import date

import pytest

from app.analytics.profiling import REQUIRED_COLUMNS, build_profile, validate_schema
from app.analytics.repository import AnalyticsRepository
from app.errors import DatasetError, QueryExecutionError


def scalar(repository: AnalyticsRepository, sql: str):
    result = repository.execute_query(sql)
    return next(iter(result.rows[0].values()))


# --- ground truth ---------------------------------------------------------


def test_top_product_by_actual_quantity(real_dataset_repository):
    result = real_dataset_repository.execute_query(
        "SELECT product_id, SUM(actual_quantity) AS total "
        "FROM sales GROUP BY product_id ORDER BY total DESC LIMIT 1"
    )

    assert result.rows[0] == {"product_id": "Product_1359", "total": 95_112_506}


def test_top_location_by_actual_quantity(real_dataset_repository):
    result = real_dataset_repository.execute_query(
        "SELECT local, SUM(actual_quantity) AS total "
        "FROM sales GROUP BY local ORDER BY total DESC LIMIT 1"
    )

    assert result.rows[0] == {"local": "Whse_J", "total": 617_421_620}


def test_total_actual_quantity(real_dataset_repository):
    assert scalar(real_dataset_repository, "SELECT SUM(actual_quantity) FROM sales") == 953_555_461


def test_total_planned_quantity(real_dataset_repository):
    assert scalar(real_dataset_repository, "SELECT SUM(planned_quantity) FROM sales") == 949_259_991


def test_gap_between_planned_and_actual(real_dataset_repository):
    gap = scalar(
        real_dataset_repository,
        "SELECT SUM(actual_quantity) - SUM(planned_quantity) FROM sales",
    )

    assert gap == 4_295_470


# --- armadilhas do dataset ------------------------------------------------


def test_row_count(real_dataset_repository):
    assert scalar(real_dataset_repository, "SELECT COUNT(*) FROM sales") == 203_635


def test_date_is_parsed_as_day_first(real_dataset_repository):
    """O CSV usa DD/MM/YYYY. Se o DuckDB inferir MM/DD, filtros por período mentem."""
    result = real_dataset_repository.execute_query(
        "SELECT MIN(date) AS first, MAX(date) AS last FROM sales"
    )

    assert result.rows[0] == {"first": date(2012, 1, 1), "last": date(2012, 12, 31)}
    assert (
        scalar(
            real_dataset_repository,
            "SELECT COUNT(*) FROM sales WHERE EXTRACT(day FROM date) > 12",
        )
        == 121_097
    )


def test_promotion_type_uses_literal_none_not_null(real_dataset_repository):
    """`IS NOT NULL` não filtra promoções: o valor ausente é a string 'None'."""
    result = real_dataset_repository.execute_query(
        "SELECT promotion_type, COUNT(*) AS n FROM sales GROUP BY 1 ORDER BY n DESC"
    )

    assert {row["promotion_type"]: row["n"] for row in result.rows} == {
        "None": 203_623,
        "Flash": 12,
    }
    assert (
        scalar(real_dataset_repository, "SELECT COUNT(*) FROM sales WHERE promotion_type IS NULL")
        == 0
    )


def test_price_only_differs_under_promotion(real_dataset_repository):
    differing = scalar(
        real_dataset_repository,
        "SELECT COUNT(*) FROM sales WHERE actual_price <> planned_price",
    )
    under_promo = scalar(
        real_dataset_repository,
        "SELECT COUNT(*) FROM sales "
        "WHERE actual_price <> planned_price AND promotion_type = 'Flash'",
    )

    assert differing == 12
    assert under_promo == 12


# --- schema e perfil ------------------------------------------------------


def test_column_names_are_the_real_ones(real_dataset_repository):
    """Confirma product_id/local e protege contra o BOM virar parte do 1o nome."""
    column_types = validate_schema(real_dataset_repository.connection)

    assert list(column_types) == list(REQUIRED_COLUMNS)
    assert "product" not in column_types
    assert "location" not in column_types


def test_profile_describes_the_dataset(real_dataset_repository):
    profile = build_profile(real_dataset_repository.connection)

    assert profile.row_count == 203_635
    assert profile.product_count == 1_966
    assert profile.locations == ["Whse_A", "Whse_C", "Whse_J", "Whse_S"]
    assert profile.promotion_types == {"None": 203_623, "Flash": 12}
    assert profile.has_nulls is False
    assert "service_level" in profile.constant_columns


# --- falhas -------------------------------------------------------------------


def test_missing_dataset_fails_with_clear_message(tmp_path):
    with pytest.raises(DatasetError) as exc_info:
        AnalyticsRepository.open(tmp_path / "nao-existe.csv")

    assert "not found" in str(exc_info.value)


def test_missing_column_is_reported_by_name(tmp_path):
    csv_path = tmp_path / "incompleto.csv"
    csv_path.write_text("product_id;local\nProduct_1;Whse_A\n", encoding="utf-8")

    repository = AnalyticsRepository.open(csv_path)
    try:
        with pytest.raises(DatasetError) as exc_info:
            validate_schema(repository.connection)
    finally:
        repository.close()

    assert "actual_quantity" in str(exc_info.value)


def test_invalid_sql_raises_query_execution_error(real_dataset_repository):
    with pytest.raises(QueryExecutionError):
        real_dataset_repository.execute_query("SELECT coluna_inexistente FROM sales")


# --- cache --------------------------------------------------------------------


def test_repeated_query_is_served_from_cache(real_dataset_repository):
    sql = "SELECT COUNT(*) AS n FROM sales WHERE local = 'Whse_C'"

    first = real_dataset_repository.execute_query(sql)
    second = real_dataset_repository.execute_query(sql)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.rows == second.rows
