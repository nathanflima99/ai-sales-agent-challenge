"""Harness de avaliação do agente contra o golden set.

Roda cada pergunta contra uma instância viva da API e verifica o resultado. Não
faz parte da suíte do `pytest`: depende de um provider configurado, é lento, e o
que ele mede é o **agente**, não o código determinístico.

A checagem central não é sobre a prosa. Para cada resposta, o SQL que o agente
escreveu é extraído do trace e **re-executado aqui** contra o mesmo DuckDB. Isso
separa duas falhas que se confundem num sistema não determinístico:

- o agente chegou ao dado certo (o SQL dele produz o valor esperado);
- o agente narrou o dado certo (o valor aparece na resposta ao usuário).

Um modelo pode acertar a primeira e errar a segunda — inventando um número na
narração — e é exatamente isso que uma asserção só sobre texto deixaria passar.

Uso:
    python evals/run_evals.py                      # usa http://localhost:8000
    python evals/run_evals.py --url http://host:8000 --only top_product
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_FILE = Path(__file__).resolve().parent / "golden_questions.yaml"
DATASET = ROOT / "dataset" / "sales.csv"

#: Marcadores de cautela amostral. O agente não precisa usar uma frase exata,
#: mas precisa registrar a limitação de alguma forma reconhecível.
HEDGE_MARKERS = (
    "amostra",
    "amostral",
    "poucos registros",
    "não é possível atribuir",
    "nao e possivel atribuir",
    "causalidade",
    "limitação",
    "limitacao",
    "12 registros",
    "12 vendas",
)


@dataclass
class Check:
    label: str
    passed: bool
    detail: str = ""


@dataclass
class Outcome:
    case_id: str
    question: str
    checks: list[Check] = field(default_factory=list)
    elapsed_s: float = 0.0
    turns: int = 0
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(check.passed for check in self.checks)


def digits(text: str) -> str:
    """Remove tudo que não for dígito, para comparar números apesar da formatação.

    O modelo escreve `95.112.506`, `95,112,506` ou `95112506` conforme o humor.
    """
    return re.sub(r"\D", "", text or "")


def ask(url: str, question: str, timeout: float) -> tuple[dict[str, Any], float]:
    started = time.perf_counter()
    response = httpx.post(f"{url}/ask", json={"question": question}, timeout=timeout)
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    return response.json(), elapsed


def rerun_agent_sql(connection: duckdb.DuckDBPyConnection, trace: list[dict]) -> str:
    """Re-executa cada SQL do trace e devolve os resultados serializados.

    É a asserção forte: o valor esperado tem de sair do banco quando a consulta
    que o agente escreveu é executada de novo, aqui, sem passar pelo modelo.
    """
    chunks: list[str] = []
    for entry in trace:
        sql = entry.get("sql")
        if not sql or entry.get("status") != "ok":
            continue
        try:
            rows = connection.execute(sql).fetchall()
        except duckdb.Error as exc:  # pragma: no cover - SQL já validado pelo guard
            chunks.append(f"<erro ao reexecutar: {exc}>")
            continue
        chunks.append(json.dumps(rows, default=str, ensure_ascii=False))
    return " ".join(chunks)


def evaluate(case: dict, body: dict, sql_output: str) -> list[Check]:
    expects = case.get("expects", {})
    answer = body.get("answer", "") or ""
    metadata = body.get("metadata", {})
    assumptions = body.get("assumptions") or []
    warnings = body.get("warnings") or []
    checks: list[Check] = []

    if "data_queried" in expects:
        actual = bool(metadata.get("data_queried"))
        checks.append(Check("consultou o dataset", actual == expects["data_queried"], f"={actual}"))

    for expected in expects.get("sql_result_contains", []):
        needle = str(expected)
        found = (
            needle in sql_output
            if not needle.isdigit()
            else needle in digits(sql_output) or needle in sql_output
        )
        checks.append(Check(f"SQL do agente produz {needle!r}", found))

    if "sql_matches" in expects:
        executed = " ".join(e.get("sql") or "" for e in metadata.get("trace", []))
        checks.append(
            Check(
                f"SQL casa com /{expects['sql_matches']}/",
                bool(re.search(expects["sql_matches"], executed)),
            )
        )

    if "answer_contains" in expects:
        checks.append(
            Check(
                f"resposta cita {expects['answer_contains']!r}",
                expects["answer_contains"].lower() in answer.lower(),
            )
        )

    if "answer_number" in expects:
        needle = str(expects["answer_number"])
        checks.append(Check(f"resposta narra o numero {needle}", needle in digits(answer)))

    if "answer_absent" in expects:
        checks.append(
            Check(
                f"resposta NAO contem {expects['answer_absent']!r}",
                expects["answer_absent"].lower() not in answer.lower(),
            )
        )

    if expects.get("declares_assumption"):
        checks.append(Check("declarou premissa", bool(assumptions), f"{len(assumptions)} item(ns)"))

    if expects.get("hedges_causality"):
        haystack = " ".join([answer, *assumptions, *warnings]).lower()
        checks.append(
            Check("registrou a limitacao amostral", any(m in haystack for m in HEDGE_MARKERS))
        )

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Roda o golden set contra a API viva.")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--only", help="roda apenas um caso, pelo id")
    args = parser.parse_args()

    cases = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
        if not cases:
            print(f"nenhum caso com id {args.only!r}")
            return 2

    if not DATASET.is_file():
        print(f"dataset nao encontrado em {DATASET}")
        return 2

    connection = duckdb.connect(database=":memory:")
    connection.execute(
        f"CREATE VIEW sales AS SELECT * FROM read_csv_auto('{DATASET.as_posix()}', delim=';')"
    )

    outcomes: list[Outcome] = []
    for index, case in enumerate(cases, 1):
        label = case["id"]
        if case.get("enunciado"):
            label += f" (enunciado #{case['enunciado']})"
        print(f"\n[{index}/{len(cases)}] {label}")
        print(f"  ? {case['question']}")

        outcome = Outcome(case_id=case["id"], question=case["question"])
        try:
            body, elapsed = ask(args.url, case["question"], args.timeout)
        except Exception as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            print(f"  ERRO: {outcome.error}")
            outcomes.append(outcome)
            continue

        outcome.elapsed_s = elapsed
        outcome.turns = int(body.get("metadata", {}).get("turns", 0))
        trace = body.get("metadata", {}).get("trace", [])
        sql_output = rerun_agent_sql(connection, trace)
        outcome.checks = evaluate(case, body, sql_output)

        for entry in trace:
            if entry.get("sql"):
                print(f"  SQL {entry['sql']}")
        for check in outcome.checks:
            mark = "ok  " if check.passed else "FALHA"
            print(f"  [{mark}] {check.label} {check.detail}")
        print(f"  {outcome.elapsed_s:.1f}s, {outcome.turns} turno(s)")
        outcomes.append(outcome)

    connection.close()

    passed = sum(1 for o in outcomes if o.passed)
    total = len(outcomes)
    print("\n" + "=" * 72)
    print(f"{'CASO':<26}{'RESULTADO':<12}{'TEMPO':<10}{'TURNOS'}")
    print("-" * 72)
    for outcome in outcomes:
        status = "APROVADO" if outcome.passed else "REPROVADO"
        print(f"{outcome.case_id:<26}{status:<12}{outcome.elapsed_s:>6.1f}s   {outcome.turns:>4}")
    print("-" * 72)

    # A média cobre apenas execuções que chegaram a responder. Incluir as que
    # falharam por transporte, cujo tempo fica em 0.0s, subestima a latência —
    # uma rodada com três erros chegou a reportar 58s onde a real era ~85s.
    timed = [o for o in outcomes if o.error is None and o.elapsed_s > 0]
    mean = sum(o.elapsed_s for o in timed) / len(timed) if timed else 0.0
    errored = sum(1 for o in outcomes if o.error is not None)

    summary = f"TAXA DE ACERTO: {passed}/{total}   tempo medio {mean:.1f}s"
    if timed:
        summary += f" (n={len(timed)})"
    if errored:
        summary += f"   {errored} sem resposta"
    print(summary)
    print("=" * 72)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
