"""Ferramentas do agente.

Três, não cinco. Cada uma resolve um problema distinto:

- `query_sales_data` é a única fonte de números da aplicação;
- `inspect_column` deixa o agente olhar os valores reais antes de filtrar;
- `submit_answer` é a única saída do grafo, o que garante resposta estruturada.

Schema e perfil do dataset **não** são ferramentas: são constantes durante a
execução e vão no system prompt. Gastar uma chamada de tool para devolver texto
fixo custa latência e tokens sem ganho nenhum.
"""

import json
import logging
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from app.analytics.profiling import DatasetProfile
from app.analytics.repository import AnalyticsRepository
from app.analytics.sql_guard import validate_sql
from app.config import Settings
from app.errors import SQLValidationError

logger = logging.getLogger(__name__)

SUBMIT_ANSWER = "submit_answer"


class FinalAnswer(BaseModel):
    """Resposta final estruturada, produzida pela tool `submit_answer`."""

    answer: str = Field(description="Resposta em linguagem natural, na língua da pergunta.")
    assumptions: list[str] = Field(
        default_factory=list,
        description="Interpretações escolhidas quando a pergunta admitia mais de uma.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Limitações do dado que afetam a leitura da resposta.",
    )


#: Profundidade máxima ao desempacotar JSON aninhado vindo do modelo.
_MAX_NORMALIZE_DEPTH = 5


def normalize_text_list(value: object, _depth: int = 0) -> list[str]:
    """Converte o que o modelo mandou numa lista de strings utilizáveis.

    Modelos pequenos não respeitam de forma confiável um schema `array of string`.
    Observado em execução real com `qwen3.5:4b`: uma string JSON no lugar da lista,
    e um objeto no lugar da lista. Um `list()` direto sobre esses valores produz
    lixo — a string vira uma lista de caracteres e o dict vira uma lista de chaves.

    Regras:
    - lista válida: mantém as strings não vazias;
    - string simples: vira um item único;
    - string contendo JSON: é parseada e normalizada recursivamente;
    - dict: normaliza os **valores**, nunca as chaves;
    - vazios e `None` são descartados.
    """
    if value is None or _depth > _MAX_NORMALIZE_DEPTH:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        # Só tenta desempacotar quando parece JSON; sem isso, toda frase comum
        # pagaria o custo de um parse que vai falhar.
        looks_like_json = text[0] in "[{" or (len(text) > 1 and text[0] == '"' == text[-1])
        if looks_like_json:
            try:
                return normalize_text_list(json.loads(text), _depth + 1)
            except (json.JSONDecodeError, ValueError):
                pass
        return [text]

    if isinstance(value, dict):
        # As chaves são nomes de campo inventados pelo modelo, não conteúdo.
        collected: list[str] = []
        for item in value.values():
            collected.extend(normalize_text_list(item, _depth + 1))
        return collected

    if isinstance(value, list | tuple):
        collected = []
        for item in value:
            collected.extend(normalize_text_list(item, _depth + 1))
        return collected

    text = str(value).strip()
    return [text] if text else []


def build_tools(
    repository: AnalyticsRepository,
    profile: DatasetProfile,
    settings: Settings,
) -> list[BaseTool]:
    """Cria as ferramentas ligadas a este repositório.

    Uma factory com closure em vez de funções de módulo com estado global: o
    repositório é criado no `lifespan` e os testes montam ferramentas sobre um CSV
    de amostra sem monkeypatch.
    """

    @tool
    def query_sales_data(sql: str) -> dict[str, Any]:
        """Executa uma consulta SQL de leitura sobre a tabela `sales` e devolve as linhas.

        Use esta ferramenta para TODO cálculo. Nunca calcule números de cabeça.

        A consulta precisa ser um único SELECT sobre a tabela `sales`. Escrita,
        múltiplas statements, outras tabelas e funções de leitura de arquivo são
        rejeitadas. Um LIMIT é aplicado automaticamente.

        Args:
            sql: A consulta SELECT a executar, no dialeto DuckDB.
        """
        validated = validate_sql(sql, max_rows=settings.max_query_rows)
        result = repository.execute_query(validated)
        payload = result.as_dict()
        payload["sql"] = validated
        payload["cache_hit"] = result.cache_hit
        return payload

    @tool
    def inspect_column(column: str) -> dict[str, Any]:
        """Mostra os valores reais de uma coluna antes de você filtrar por ela.

        Use antes de escrever qualquer `WHERE` sobre coluna categórica. Filtrar por
        um valor que você supôs, e que não existe no dataset, devolve zero linhas
        sem erro nenhum — e a resposta sai errada com aparência de certa.

        Args:
            column: Nome da coluna a inspecionar.
        """
        if column not in profile.columns:
            raise SQLValidationError(
                f"Column '{column}' does not exist. Available columns: {', '.join(profile.columns)}"
            )

        # O nome já foi validado contra o schema real, então a interpolação abaixo
        # não pode receber texto arbitrário do modelo.
        result = repository.execute_query(
            f'SELECT DISTINCT "{column}" AS value, COUNT(*) AS occurrences '
            f'FROM sales GROUP BY "{column}" ORDER BY occurrences DESC LIMIT 20'
        )
        distinct_total = repository.execute_query(
            f'SELECT COUNT(DISTINCT "{column}") AS n FROM sales'
        ).rows[0]["n"]

        return {
            "column": column,
            "dtype": profile.column_types[column],
            "distinct_count": distinct_total,
            "null_count": profile.null_counts[column],
            "most_common_values": result.rows,
            "truncated": distinct_total > len(result.rows),
        }

    @tool(SUBMIT_ANSWER)
    def submit_answer(
        answer: str,
        assumptions: list[str] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        """Entrega a resposta final ao usuário. Sempre termine chamando esta ferramenta.

        Args:
            answer: A resposta em linguagem natural, na mesma língua da pergunta.
                Cite os números que vieram das consultas.
            assumptions: Interpretações que você escolheu quando a pergunta admitia
                mais de uma leitura razoável. Ex.: se "total de vendas" pode ser
                quantidade ou faturamento, diga qual você usou e que a outra existe.
            warnings: Limitações do dado que mudam como a resposta deve ser lida.
                Ex.: amostra pequena demais para sustentar a conclusão pedida.
        """
        final = FinalAnswer(
            answer=answer,
            assumptions=normalize_text_list(assumptions),
            warnings=normalize_text_list(warnings),
        )
        logger.info(
            "final answer submitted",
            extra={
                "assumptions": len(final.assumptions),
                "warnings": len(final.warnings),
            },
        )
        return final.model_dump()

    return [query_sales_data, inspect_column, submit_answer]
