"""Verificacao de que os numeros da resposta vieram das consultas.

A regra "o DuckDB calcula" vivia so no prompt, e instrucao e seguida de forma
probabilistica. Medido com `qwen3.5:4b`: perguntado pela diferenca entre
planejado e realizado, o modelo consultou as duas somas e subtraiu na resposta,
errando o valor em 10.000 e o sinal. A conta era o enunciado da pergunta.

Este modulo transforma a regra em verificacao: todo numero apresentado ao
usuario precisa aparecer em algum resultado de consulta. O que nao aparecer
volta ao modelo como observacao, no mesmo mecanismo que trata erro de
ferramenta.

Duas decisoes de precisao que custaram bugs para aprender:

- **O sinal conta.** Comparar so digitos faz um resultado de `-4295470`
  autorizar a alegacao `+4295470`, que e exatamente o erro que motivou a trava.
- **SQL nao e evidencia.** O payload da ferramenta carrega a consulta junto com
  as linhas, e a consulta foi escrita pelo modelo. Sem excluir o SQL, um
  `WHERE actual_quantity > 9876` autorizaria a alegacao `9876`.
"""

import re
from typing import Any

#: Numeros de um digito nao sao verificados: marcadores de lista, "2 produtos",
#: "os 3 primeiros" geram falso positivo constante e carregam pouco risco. De
#: dois digitos em diante entra tudo, inclusive percentuais e contagens como as
#: 12 promocoes deste dataset, que sao justamente fatos centrais dele.
MIN_DIGITS = 2

#: Faixa tratada como ano. `2012` aparece o tempo todo aqui sem ser conta.
YEAR_RANGE = range(1900, 2101)

#: Chaves do payload que nao sao resultado do banco. `sql` e texto escrito pelo
#: proprio modelo; aceita-lo como evidencia deixaria o modelo se autorizar.
NON_EVIDENCE_KEYS = frozenset({"sql", "args", "column"})

#: Captura o sinal e exige que o numero esteja isolado. Sem as bordas,
#: `Product_1359` viraria a alegacao numerica `1359`, e `2012-01-01` viraria um
#: `-01` negativo.
_NUMBER = re.compile(r"(?<![\w-])(-?)(\d[\d.,]*\d|\d)(?!\w)")


def digits_of(text: str) -> str:
    """So os digitos, para comparar apesar da formatacao.

    O modelo escreve `95.112.506`, `95,112,506` ou `95112506` conforme o humor.
    """
    return re.sub(r"\D", "", text or "")


def _normalize(sign: str, raw: str) -> str | None:
    value = digits_of(raw).lstrip("0")
    if not value:
        return "0" if digits_of(raw) else None
    return f"{sign}{value}"


def numbers_in(text: str) -> set[str]:
    """Extrai os numeros de um texto, com sinal, normalizados para digitos."""
    found: set[str] = set()
    for match in _NUMBER.finditer(text or ""):
        value = _normalize(match.group(1), match.group(2))
        if value is not None:
            found.add(value)
    return found


def numbers_in_payload(payload: Any) -> set[str]:
    """Extrai os numeros de um resultado de ferramenta, preservando o sinal.

    Ignora as chaves que nao sao resultado do banco (ver `NON_EVIDENCE_KEYS`) e
    registra os arredondamentos a uma e duas casas, porque `154354899659.2`
    costuma ser narrado como `154.354.899.659,20`.
    """
    found: set[str] = set()

    def add(value: float | int) -> None:
        sign = "-" if value < 0 else ""
        magnitude = abs(value)
        if isinstance(value, int):
            found.add(f"{sign}{str(magnitude).lstrip('0') or '0'}")
            return
        for rendered in (repr(magnitude), f"{magnitude:.1f}", f"{magnitude:.2f}"):
            digits = digits_of(rendered).lstrip("0")
            if digits:
                found.add(f"{sign}{digits}")

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key not in NON_EVIDENCE_KEYS:
                    walk(item)
        elif isinstance(node, list | tuple):
            for item in node:
                walk(item)
        elif isinstance(node, bool):
            return
        elif isinstance(node, int | float):
            add(node)
        elif isinstance(node, str):
            found.update(numbers_in(node))

    walk(payload)
    return found


def _is_rounding_of(candidate: str, known: set[str]) -> bool:
    """Aceita `95,1 milhoes` como narracao de `95.112.506`.

    Um arredondamento e um prefixo dos digitos do valor original, com o mesmo
    sinal. Exigir os digitos exatos transformaria toda narracao aproximada em
    falso positivo; ignorar o sinal deixaria passar a inversao.
    """
    negative = candidate.startswith("-")
    digits = candidate.lstrip("-")
    for source in known:
        if source.startswith("-") != negative:
            continue
        source_digits = source.lstrip("-")
        if len(source_digits) > len(digits) and source_digits.startswith(digits):
            return True
    return False


def unverified_numbers(claims: str, question: str, result_numbers: set[str]) -> list[str]:
    """Devolve os numeros apresentados ao usuario que nenhuma consulta produziu.

    `claims` deve conter tudo que o usuario ve: resposta, premissas e ressalvas.
    Um numero inventado numa premissa engana tanto quanto um inventado na
    resposta.

    Ignora, por serem fonte de falso positivo e nao de risco:

    - numeros de um digito;
    - anos;
    - numeros que ja estavam na pergunta;
    - arredondamentos de um valor que veio de consulta.
    """
    from_question = numbers_in(question)
    unverified: list[str] = []

    for candidate in sorted(numbers_in(claims), key=len, reverse=True):
        digits = candidate.lstrip("-")
        if len(digits) < MIN_DIGITS:
            continue
        if candidate in result_numbers or candidate in from_question:
            continue
        if len(digits) == 4 and int(digits) in YEAR_RANGE:
            continue
        if _is_rounding_of(candidate, result_numbers):
            continue
        unverified.append(candidate)

    return unverified


def correction_message(unverified: list[str]) -> str:
    """Texto devolvido ao modelo quando um numero nao e rastreavel.

    Escrito para o modelo agir, nao para o humano ler: diz o que houve, por que
    e problema, e qual e o caminho de saida.
    """
    listed = ", ".join(unverified)
    return (
        f"The following numbers in your answer did not come from any query "
        f"result: {listed}. You may have calculated them yourself, which is not "
        f"allowed - arithmetic must be done by the database. Run a query that "
        f"computes the value directly (for example "
        f"`SELECT SUM(a) - SUM(b) AS diff FROM sales`), then call submit_answer "
        f"again citing only numbers the query returned."
    )
