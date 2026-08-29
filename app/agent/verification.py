"""Verificacao de que os numeros da resposta vieram das consultas.

A regra "o DuckDB calcula" vivia so no prompt, e instrucao e seguida de forma
probabilistica. Medido com `qwen3.5:4b`: perguntado pela diferenca entre
planejado e realizado, o modelo consultou as duas somas e subtraiu na resposta,
errando o valor em 10.000 e o sinal. A conta era o enunciado da pergunta.

Este modulo transforma a regra em verificacao: todo numero da resposta precisa
aparecer em algum resultado de consulta. O que nao aparecer volta ao modelo como
observacao, no mesmo mecanismo que trata erro de ferramenta.

O desenho e conservador de proposito. Um falso positivo custa um turno e irrita;
se forem frequentes, alguem desliga a trava e ela deixa de existir. Por isso a
verificacao ignora as categorias em que um numero legitimo pode nao estar
literalmente num resultado.
"""

import re
from typing import Any

#: Abaixo disto, o numero e curto demais para carregar risco e comum demais para
#: verificar: contagens pequenas, posicoes de ranking, percentuais.
MIN_DIGITS = 4

#: Faixa tratada como ano. `2012` aparece o tempo todo neste dataset sem ser
#: resultado de conta.
YEAR_RANGE = range(1900, 2101)

#: So numeros isolados. Sem as bordas, `Product_1359` viraria a alegacao numerica
#: `1359` e a verificacao reprovaria a resposta certa: identificador nao e conta.
_NUMBER = re.compile(r"(?<!\w)\d[\d.,]*\d(?!\w)|(?<!\w)\d(?!\w)")


def digits_of(text: str) -> str:
    """So os digitos, para comparar apesar da formatacao.

    O modelo escreve `95.112.506`, `95,112,506` ou `95112506` conforme o humor.
    """
    return re.sub(r"\D", "", text or "")


def numbers_in(text: str) -> set[str]:
    """Extrai os numeros de um texto, normalizados para sequencia de digitos."""
    found: set[str] = set()
    for match in _NUMBER.finditer(text or ""):
        value = digits_of(match.group())
        if value:
            found.add(value.lstrip("0") or "0")
    return found


def numbers_in_payload(payload: Any) -> set[str]:
    """Extrai recursivamente os numeros de um resultado de ferramenta.

    Tambem registra os valores arredondados a uma e duas casas, porque
    `154354899659.2` costuma ser narrado como `154.354.899.659,20`.
    """
    found: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, list | tuple):
            for item in node:
                walk(item)
        elif isinstance(node, bool):
            return
        elif isinstance(node, int):
            found.add(str(abs(node)).lstrip("0") or "0")
        elif isinstance(node, float):
            for rendered in (repr(abs(node)), f"{abs(node):.1f}", f"{abs(node):.2f}"):
                value = digits_of(rendered).lstrip("0")
                if value:
                    found.add(value)
        elif isinstance(node, str):
            found.update(numbers_in(node))

    walk(payload)
    return found


def _is_rounding_of(candidate: str, known: set[str]) -> bool:
    """Aceita `95,1 milhoes` como narracao de `95.112.506`.

    Um arredondamento e um prefixo dos digitos do valor original. Exigir os
    digitos exatos transformaria toda narracao aproximada em falso positivo.
    """
    return any(source.startswith(candidate) for source in known if len(source) > len(candidate))


def unverified_numbers(answer: str, question: str, result_numbers: set[str]) -> list[str]:
    """Devolve os numeros da resposta que nao vieram de nenhuma consulta.

    Ignora, por serem fonte de falso positivo e nao de risco:

    - numeros curtos (menos de `MIN_DIGITS` digitos);
    - anos;
    - numeros que ja estavam na pergunta;
    - arredondamentos de um valor que veio de consulta.
    """
    from_question = numbers_in(question)
    unverified: list[str] = []

    for candidate in sorted(numbers_in(answer), key=len, reverse=True):
        if len(candidate) < MIN_DIGITS:
            continue
        if candidate in result_numbers or candidate in from_question:
            continue
        if len(candidate) == 4 and int(candidate) in YEAR_RANGE:
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
