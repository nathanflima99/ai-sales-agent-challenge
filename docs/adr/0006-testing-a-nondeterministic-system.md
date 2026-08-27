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

Golden set com as cinco perguntas do enunciado mais casos de comportamento
(ambiguidade declarada, cautela com causalidade, recusa fora de escopo).

A asserção primária é sobre o **resultado da ferramenta no trace**, não sobre a
prosa: o número saiu do DuckDB, e é ali que se verifica. A asserção secundária
compara o texto com os dígitos normalizados, para confirmar que o modelo narrou o
número que a consulta devolveu em vez de inventar outro.

Isso separa duas falhas diferentes: *o agente chegou ao dado certo* e *o agente
narrou o dado certo*.

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

As camadas 1 e 2 estão implementadas (100 testes). A camada 3 depende de uma
credencial de provider, que ainda não existe neste ambiente — ver a seção de
limitações conhecidas no README.
