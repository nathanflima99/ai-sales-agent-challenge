# ADR 0004 — Três ferramentas, e o critério de tool vs prompt

## Contexto

Um agente pode expor quantas ferramentas quiser. Cada ferramenta adicional gasta
tokens na descrição, aumenta a chance de escolha errada e adiciona um caminho a
testar.

## Decisão

Três ferramentas: `query_sales_data`, `inspect_column` e `submit_answer`.

O critério: **tool serve para o que é dinâmico; prompt serve para o que é fixo.**

## Consequências

### `query_sales_data`

Única fonte de números da aplicação. Devolve no payload o SQL efetivamente
executado, que sobe para o `metadata.trace` da resposta — é o que permite a quem
lê reconferir qualquer número à mão.

### `inspect_column`

Existe por causa de uma armadilha concreta e verificada deste dataset:
`promotion_type` **não tem NULL**. A ausência de promoção é a string literal
`'None'`. Um `WHERE promotion_type IS NOT NULL` devolve as 203.635 linhas sem
erro nenhum, e a resposta sai errada com aparência de correta.

Esta é a classe de bug mais perigosa num sistema desses: ele não falha, mente.
A ferramenta deixa o agente olhar os valores reais antes de filtrar. Cinto e
suspensório: o valor também está descrito no system prompt.

### `submit_answer`

Única saída do grafo. Recebe `answer`, `assumptions` e `warnings`.

Sem ela, esses campos existiriam no schema da resposta e ficariam vazios na
prática — era um furo do plano original, que os declarava sem definir como o
modelo os produziria. Fazendo dela a única aresta para `END`, o contrato passa a
ser garantido pelo **grafo**, não pela cooperação do modelo.

## O que ficou fora

**Schema e perfil do dataset não são ferramentas.** São constantes durante toda a
execução e vão no system prompt. Gastar uma chamada de ferramenta — latência mais
tokens de ida e volta — para devolver texto que nunca muda não compra nada.

## O que o prompt deliberadamente não contém

O perfil vai para o prompt, mas **os agregados não**. Se `Product_1359` e
`953.555.461` estivessem lá, o modelo poderia respondê-los sem consultar, e a
regra de nunca calcular de cabeça viraria letra morta. Há um teste asserindo essa
ausência.
