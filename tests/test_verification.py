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

    assert unverified == ["-4305470"]


def test_the_sign_is_part_of_the_claim():
    """Um resultado negativo não autoriza a alegação positiva.

    Sem isto, um `-4295470` vindo do banco validaria a resposta `4295470` — que
    é exatamente a inversão de sinal que motivou a trava.
    """
    results = numbers_in_payload({"rows": [{"diferenca": -4295470}]})

    assert check("A diferença é de 4.295.470 unidades.", results) == ["4295470"]
    assert check("A diferença é de -4.295.470 unidades.", results) == []


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


def test_rounding_up_is_accepted_only_in_the_right_direction():
    """Quem decide é o dígito descartado, não uma tolerância.

    Uma tolerância de 1 no prefixo validava `94 milhões` e `96 milhões` para o
    mesmo 95.112.506 — e nenhum dos dois é o arredondamento correto.
    """
    de_95_5 = numbers_in_payload({"rows": [{"total": 95512506}]})
    assert check("Foram cerca de 96 milhões.", de_95_5) == []  # 95|5... arredonda pra 96

    de_95_1 = numbers_in_payload({"rows": [{"total": 95112506}]})
    assert check("Foram cerca de 95 milhões.", de_95_1) == []  # truncamento
    assert check("Foram cerca de 96 milhões.", de_95_1) == ["96"]  # 95|1... não sobe
    assert check("Foram cerca de 94 milhões.", de_95_1) == ["94"]  # nem desce


def test_a_different_number_is_not_a_rounding():
    """A tolerância é de 1 no último dígito mantido, não uma licença.

    `4305470` contra `4295470` difere em 10.000 — é o bug original, não
    arredondamento.
    """
    results = numbers_in_payload({"rows": [{"diferenca": 4295470}]})

    assert check("A diferença é 4.305.470.", results) == ["4305470"]


def test_date_components_are_not_claims():
    """O `31` de `31/12/2012` não é uma conta.

    Falso positivo real: reprovado três vezes numa medição de 32 execuções.
    """
    assert check("O período vai de 01/01/2012 a 31/12/2012.", set()) == []


def test_a_ratio_is_not_masked_as_a_date():
    """`60/30/10` tem forma de data e não é uma.

    Sem validar o calendário, a máscara escondia as três alegações antes da
    verificação, e a resposta passava como verificada.
    """
    assert sorted(check("A composição foi 60/30/10.", set())) == ["10", "30", "60"]


def test_both_date_orders_are_recognized():
    """O CSV traz DD/MM/YYYY e o DuckDB devolve YYYY-MM-DD."""
    assert check("De 2012-01-01 até 31/12/2012.", set()) == []


def test_the_date_exemption_is_positional_not_by_value():
    """Mascarar a data, não liberar o valor dela.

    Isentar por valor deixava passar o `31` da contagem só porque o mesmo 31
    aparecia numa data ao lado.
    """
    assert check("Houve 31 vendas em 31/12/2012.", set()) == ["31"]


def test_rounding_that_grows_a_digit():
    """`99512506` narrado como `100 milhões` cresce de dois para três dígitos."""
    results = numbers_in_payload({"rows": [{"total": 99512506}]})

    assert check("Foram cerca de 100 milhões.", results) == []


def test_profile_facts_count_as_query_evidence():
    """Os números do perfil vêm de SQL, só que rodado no startup.

    O agente semeia a evidência com eles, então citar as 203.635 linhas não é
    exceção à regra — é um número que veio mesmo do banco. Falso positivo real:
    reprovado duas vezes numa medição de 32 execuções.
    """
    unverified = unverified_numbers(
        "O dataset tem 203.635 linhas e 1.966 produtos.",
        "Pergunta",
        result_numbers={"203635", "1966"},
    )

    assert unverified == []


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


def test_single_digits_are_ignored():
    """Marcadores de lista e contagens de um dígito geram ruído constante."""
    assert check("Foram 2 produtos, os 3 primeiros, 1 ano.", set()) == []


def test_two_digit_claims_are_verified():
    """`12 promoções` e `20%` são fatos centrais deste dataset.

    Isentá-los por serem curtos deixaria o modelo inventar exatamente as métricas
    que mais importam aqui.
    """
    assert sorted(check("Foram 13 promoções com 25% de desconto.", set())) == ["13", "25"]

    results = numbers_in_payload({"rows": [{"n": 12}]})
    assert check("Foram 12 promoções.", results) == []


def test_sql_text_is_not_evidence():
    """A consulta é escrita pelo modelo; aceitá-la o deixaria se autorizar.

    Sem excluir o SQL do payload, um `WHERE actual_quantity > 9876` validaria a
    alegação de que o total é 9876.
    """
    payload = {
        "sql": "SELECT SUM(actual_quantity) FROM sales WHERE actual_quantity > 9876",
        "rows": [{"total": 33978}],
    }

    results = numbers_in_payload(payload)

    assert "9876" not in results
    assert check("O total foi 9876.", results) == ["9876"]
    assert check("O total foi 33978.", results) == []


def test_claims_cover_assumptions_and_warnings():
    """Premissas e ressalvas também aparecem na resposta da API."""
    results = numbers_in_payload({"rows": [{"total": 33978}]})
    claims = "\n".join(["O total foi 33978.", "Considerei 10000 registros."])

    assert check(claims, results) == ["10000"]


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
