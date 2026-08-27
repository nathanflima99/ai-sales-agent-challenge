"""Acesso analítico ao dataset via DuckDB.

O CSV é exposto como uma view somente leitura chamada `sales`. Toda agregação,
filtro e ordenação acontece aqui — nenhum número apresentado ao usuário sai da
inferência do modelo.
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

import duckdb

from app.errors import DatasetError, QueryExecutionError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class QueryResult:
    """Resultado de uma consulta, pronto para virar payload de tool."""

    columns: list[str]
    rows: list[dict[str, Any]]
    elapsed_ms: float
    cache_hit: bool = False
    truncated: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def as_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
        }


@dataclass(slots=True)
class _QueryCache:
    """LRU pequeno, protegido por lock.

    O FastAPI executa handlers síncronos num threadpool, então dois requests podem
    tocar o cache ao mesmo tempo. `OrderedDict` não é thread-safe para a sequência
    ler-mover-escrever, daí o lock explícito.
    """

    maxsize: int = 128
    _entries: OrderedDict[str, QueryResult] = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @staticmethod
    def key(sql: str) -> str:
        return hashlib.sha256(sql.encode("utf-8")).hexdigest()

    def get(self, sql: str) -> QueryResult | None:
        cache_key = self.key(sql)
        with self._lock:
            entry = self._entries.get(cache_key)
            if entry is None:
                return None
            self._entries.move_to_end(cache_key)
            return entry

    def put(self, sql: str, result: QueryResult) -> None:
        cache_key = self.key(sql)
        with self._lock:
            self._entries[cache_key] = result
            self._entries.move_to_end(cache_key)
            while len(self._entries) > self.maxsize:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class AnalyticsRepository:
    """Conexão DuckDB em memória com `sales.csv` registrado como view."""

    def __init__(self, connection: duckdb.DuckDBPyConnection, cache_size: int = 128) -> None:
        self._connection = connection
        self._cache = _QueryCache(maxsize=cache_size)

    @classmethod
    def open(cls, dataset_path: Path, cache_size: int = 128) -> Self:
        """Abre a conexão e registra a view. Falha aqui é falha de startup."""
        if not dataset_path.is_file():
            raise DatasetError(f"Dataset file not found at '{dataset_path}'")

        connection = duckdb.connect(database=":memory:")
        # View e não CREATE TABLE: o DuckDB lê o CSV sob demanda em vez de
        # materializar 200k linhas numa segunda cópia em memória.
        # `as_posix` normaliza o caminho no Windows; as aspas simples são escapadas
        # porque o caminho vem de configuração, não de entrada de usuário.
        literal_path = dataset_path.as_posix().replace("'", "''")
        try:
            connection.execute(
                f"CREATE VIEW sales AS SELECT * FROM read_csv_auto('{literal_path}', delim=';')"
            )
            connection.execute("SELECT 1 FROM sales LIMIT 1").fetchall()
        except duckdb.Error as exc:
            connection.close()
            raise DatasetError(f"Could not read dataset at '{dataset_path}': {exc}") from exc

        logger.info("dataset registered", extra={"dataset_path": str(dataset_path)})
        return cls(connection, cache_size=cache_size)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._connection

    def execute_query(self, sql: str) -> QueryResult:
        """Executa SQL já validado e devolve linhas mais metadados de execução.

        O SQL precisa ter passado pelo guard (Fase 3) antes de chegar aqui.
        """
        cached = self._cache.get(sql)
        if cached is not None:
            logger.info("query cache hit", extra={"sql": sql})
            return QueryResult(
                columns=cached.columns,
                rows=cached.rows,
                elapsed_ms=cached.elapsed_ms,
                cache_hit=True,
                truncated=cached.truncated,
            )

        started = time.perf_counter()
        # Um cursor por consulta: a conexão DuckDB não suporta uso simultâneo entre
        # threads, e o FastAPI despacha handlers síncronos num threadpool.
        cursor = self._connection.cursor()
        try:
            cursor.execute(sql)
            description = cursor.description or []
            columns = [str(column[0]) for column in description]
            rows = [dict(zip(columns, record, strict=True)) for record in cursor.fetchall()]
        except duckdb.Error as exc:
            raise QueryExecutionError(str(exc).strip()) from exc
        finally:
            cursor.close()

        elapsed_ms = (time.perf_counter() - started) * 1000
        result = QueryResult(columns=columns, rows=rows, elapsed_ms=elapsed_ms)

        self._cache.put(sql, result)
        logger.info(
            "query executed",
            extra={"sql": sql, "row_count": result.row_count, "elapsed_ms": round(elapsed_ms, 2)},
        )
        return result

    def close(self) -> None:
        self._cache.clear()
        self._connection.close()
