# ADR 0002 — LangGraph com `StateGraph` explícito, não `create_react_agent`

## Contexto

O enunciado pede explicitamente o uso de uma biblioteca de agentes de IA. O ciclo
necessário é `pergunta -> tool call -> observação -> replanejamento -> resposta`,
com recuperação de falha de ferramenta.

O LangGraph oferece o prebuilt `create_react_agent`, que monta esse loop em uma
linha.

## Decisão

Usar LangGraph, mas construindo o `StateGraph` explicitamente, com três nós
(`agent`, `tools`, `finish`) e uma aresta condicional. Não usar o prebuilt.

## Consequências

**Positivas**

- As três coisas que esta aplicação precisa expor são código nosso e ficam
  visíveis: o **trace** de cada chamada (com o SQL executado), a **cota de
  turnos** e o **tratamento de erro de ferramenta**. No prebuilt, as três são
  detalhe interno.
- O nó de tools não deixa exceção escapar: `SQLValidationError` e
  `QueryExecutionError` viram `ToolMessage` e voltam ao modelo. É isto que faz do
  sistema um agente e não um tradutor de texto para SQL — ele observa o resultado
  da própria ação e corrige o curso.
- O estado é explícito (`messages`, `turns`, `trace`, `final`), então o que a API
  devolve é exatamente o que o grafo produziu.

**Negativas**

- ~200 linhas a mais do que a versão prebuilt.
- Somos responsáveis por casos que o prebuilt trataria, como o modelo responder
  sem chamar ferramenta nenhuma.

## Alternativas rejeitadas

**`create_react_agent`** — resolve o loop, mas esconde justamente o que
precisamos mostrar e discutir.

**Loop próprio sem biblioteca** — cabe em ~60 linhas e foi a primeira intenção,
mas contraria uma instrução literal do enunciado. Com o LangGraph, `MemorySaver`
para conversas multi-turno e `astream_events` para streaming vêm quase de graça.

## Sobre o loop infinito

Duas travas, deliberadamente redundantes: um contador de turnos no estado, que
levanta `AgentLoopError` com mensagem legível, e o `recursion_limit` do próprio
LangGraph como rede de segurança. A primeira é a que dá diagnóstico; a segunda
protege de um erro de roteamento nosso.
