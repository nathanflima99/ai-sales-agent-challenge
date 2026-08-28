# ADR 0006 — Como testar um sistema não determinístico

## Contexto

O agente depende de um LLM. A mesma pergunta pode gerar SQL diferente a cada
execução, e a resposta é texto livre. Testes de igualdade exata sobre a saída do
modelo seriam instáveis por natureza.

Ao mesmo tempo, a aplicação precisa de garantias fortes: os números têm que estar
certos.

## Decisão

Separar em três camadas, com naturezas diferentes.

### 1. Ground truth — determinístico, sem IA

`tests/test_ground_truth.py` roda SQL direto contra o dataset real e asserta
valores exatos, conferidos previamente:

| Query | Valor |
|---|---|
| Top produto | `Product_1359` / 95.112.506 |
| Top local | `Whse_J` / 617.421.620 |
| `SUM(actual_quantity)` | 953.555.461 |
| `SUM(planned_quantity)` | 949.259.991 |
| Diferença | 4.295.470 |

Se um teste daqui falhar, é o código que está errado — nunca o número.

Junto vão as **armadilhas do dataset**, que quebrariam em silêncio: a data é
`DD/MM/YYYY` (121.097 linhas com dia > 12 forçam a inferência correta),
`promotion_type` usa a string `'None'` e não NULL, e o preço só difere do
planejado nas 12 linhas de promoção.

### 2. Comportamento do agente — com modelo falso

`tests/test_agent.py` programa as respostas do modelo e verifica o **grafo**:
fluxo feliz, self-correction após SQL rejeitado, cota de turnos, ferramenta
desconhecida, e resposta em prosa sem `submit_answer`.

Isso testa a máquina de estados, que é determinística, sem depender do que o
modelo decide. Não consome tokens e roda sem rede.

`FakeMessagesListChatModel` do langchain-core **não implementa `bind_tools`**,
que é exatamente o que o agente usa — daí o `ScriptedChatModel` próprio em
`tests/fakes.py`.

### 3. Evals — com modelo real

`evals/golden_questions.yaml` traz as cinco perguntas do enunciado mais três casos
de comportamento: ambiguidade declarada, armadilha do `promotion_type = 'None'`, e
recusa fora de escopo.

A asserção central **não é sobre a prosa**. O `ToolTrace` guarda o SQL executado,
então `evals/run_evals.py` extrai esse SQL e o **re-executa contra o mesmo DuckDB**,
verificando se produz o valor esperado. Uma asserção secundária compara o texto da
resposta com os dígitos normalizados — o modelo escreve `95.112.506`, `95,112,506`
ou `95112506` conforme o humor, e comparar strings cruas falharia com o agente
certo.

Isso separa duas falhas que se confundem num sistema não determinístico:

- **o agente chegou ao dado certo** — o SQL dele, reexecutado, produz o valor;
- **o agente narrou o dado certo** — o valor aparece na resposta ao usuário.

Um modelo pode acertar a primeira e errar a segunda, inventando um número na
narração. Uma asserção só sobre texto deixaria isso passar; uma asserção só sobre
o SQL não perceberia que o usuário recebeu outro número.

O harness também registra `data_queried`, que é o único fato verificável sobre a
fundamentação da resposta. Ele informa em vez de bloquear: a recusa de uma
previsão para 2030 legitimamente não consulta nada.

## Consequências

- `pytest` roda sem rede e sem chave: os evals ficam fora da suíte padrão, atrás
  do marker `integration`.
- Trocar de modelo deixa de ser opinião. Roda-se o golden set nos dois e
  compara-se a taxa de acerto.

## Alternativa rejeitada

**LLM-as-judge** — introduz um segundo sistema não determinístico para avaliar o
primeiro. Para perguntas cuja resposta correta é um número conhecido, comparar com
o número é mais barato, mais rápido e não tem margem de discordância.

## Estado

As três camadas estão implementadas. As camadas 1 e 2 somam 124 testes que rodam
sem rede em ~25s. A camada 3 foi executada contra `qwen3.5:4b` servido por Ollama;
o resultado está na seção de validação do README.

Rodar o golden set custa ~12 minutos, porque cada pergunta leva ~90s num modelo de
4B — praticamente todo esse tempo é inferência, não consulta: o DuckDB responde em
milissegundos. É por isso que ele fica fora do `pytest` padrão.
