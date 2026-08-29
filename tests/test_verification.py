"""A trava que exige que os números da resposta tenham vindo de uma consulta.

O desenho é assimétrico de propósito: reprovar um número inventado importa mais
do que aprovar todos os legítimos, mas um falso positivo custa um turno e irrita
— e uma trava que irrita é desligada, deixando de existir. Metade destes testes
existe para garantir que ela fica quieta quando deve.
"""

from app.agent.verification import (
    numbers_in,
    numbers_in_payload,
    unverified_numbers,
)


def check(answer: str, results: set[str], question: str = "Pergunta") -> list[str]:
    return unverified_numbers(answer, question, results)


# --- o caso que motivou a trava ----------------------------------------------


def test_arithmetic_done_by_the_model_is_caught():
    """O caso real: consultou as duas somas e subtraiu na resposta.

    Medido com qwen3.5:4b — respondeu -4.305.470 onde o correto era 4.295.470,
    errando valor e sinal, com os dois operandos corretos ao lado.
    """
    results = numbers_in_payload({"rows": [{"planned": 949259991, "actual": 953555461}]})

    unverified = check(
        "A diferença é de -4.305.470 unidades. Planejado: 949.259.991. Realizado: 953.555.461.",
        results,
    )

    assert unverified == ["4305470"]


def test_the_same_answer_passes_when_the_database_did_the_subtraction():
    results = numbers_in_payload({"rows": [{"diferenca": 4295470}]})

    assert check("A diferença é de 4.295.470 unidades.", results) == []


# --- não pode reprovar o que é legítimo --------------------------------------


def test_formatting_does_not_matter():
    results = numbers_in_payload({"rows": [{"total": 95112506}]})

    for rendered in ("95.112.506", "95,112,506", "95112506"):
        assert check(f"O total foi {rendered}.", results) == []


def test_rounded_narration_is_accepted():
    """`cerca de 95,1 milhões` é narração honesta de 95.112.506."""
    results = numbers_in_payload({"rows": [{"total": 95112506}]})

    assert check("Foram cerca de 95,1 milhões de unidades.", results) == []


def test_identifiers_with_digits_are_not_numeric_claims():
    """`Product_1359` é um nome, não uma conta."""
    assert check("Product_1359 foi o mais vendido.", set()) == []


def test_years_are_not_treated_as_computed_values():
    assert check("O dataset cobre 2012, de 2012-01-01 a 2012-12-31.", set()) == []


def test_numbers_from_the_question_are_allowed():
    unverified = unverified_numbers(
        "No primeiro trimestre de 2012 houve 1500 registros.",
        "Quantos registros houve nos primeiros 1500 dias?",
        set(),
    )

    assert unverified == []


def test_short_numbers_are_ignored():
    """Contagens pequenas e percentuais geram ruído sem carregar risco."""
    assert check("Foram 12 promoções, 2 produtos, alta de 20%.", set()) == []


def test_float_results_match_their_narration():
    results = numbers_in_payload({"rows": [{"faturamento": 154354899659.2}]})

    assert check("O faturamento foi 154.354.899.659,20.", results) == []


# --- extração ----------------------------------------------------------------


def test_numbers_are_found_inside_nested_payloads():
    found = numbers_in_payload({"rows": [{"a": 12, "b": {"c": [34567]}}], "row_count": 1})

    assert "12" in found
    assert "34567" in found


def test_booleans_are_not_numbers():
    assert numbers_in_payload({"cache_hit": True, "truncated": False}) == set()


def test_leading_zeros_are_normalized():
    assert numbers_in("007") == {"7"}
