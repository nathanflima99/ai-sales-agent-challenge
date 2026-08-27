# ADR 0005 — Não usar `create_csv_agent` / `create_pandas_dataframe_agent`

## Contexto

O enunciado pede um agente que analise um CSV, usando uma biblioteca de agentes de
IA. O LangChain oferece exatamente isso, pronto:

```python
from langchain_experimental.agents import create_csv_agent
agent = create_csv_agent(llm, "sales.csv", allow_dangerous_code=True)
```

Duas linhas resolveriam o desafio inteiro.

## Decisão

Não usar. O agente gera **SQL validado**, nunca Python.

## O motivo

Esses agentes funcionam colocando um `PythonAstREPLTool` na mão do modelo:
ele escreve código Python e o agente **executa** esse código no processo da
aplicação. A própria biblioteca exige `allow_dangerous_code=True` para deixar
isso claro.

Isso é execução remota de código por construção. O modelo é influenciado pelo
texto da pergunta do usuário, então a superfície de ataque é:

```
usuário -> pergunta -> LLM -> código Python -> exec() no servidor
```

Não há sandbox aí. Um `__import__('os').system(...)` gerado por injeção de prompt
roda com os privilégios do processo. Num container com credenciais de API em
variável de ambiente, isso vaza a chave na primeira tentativa.

## A alternativa escolhida

```
usuário -> pergunta -> LLM -> SQL -> validação de AST -> DuckDB somente leitura
```

O SQL é uma linguagem **restrita**: não tem `import`, não tem acesso a processo,
não tem rede. E é analisável — dá para provar que uma consulta só lê a tabela
`sales` antes de executá-la, o que é impossível de fazer com Python arbitrário.

## Consequências

**Positivas**

- A superfície de execução é conhecida e testada (ver
  [ADR 0003](0003-sqlglot-ast-validation.md)).
- Cada resposta é auditável: o SQL executado aparece no trace.
- Continuamos usando a biblioteca que o enunciado pede — apenas não usamos o
  atalho inseguro dela.

**Negativas**

- Mais código: guard, repositório e ferramentas em vez de duas linhas.
- Perguntas que exigiriam manipulação fora do alcance do SQL não são atendidas.
  Nenhuma apareceu no escopo.

## Regra derivada

`exec`, `eval` e `PythonAstREPLTool` são proibidos no repositório. A regra está no
`AGENTS.md` e é o primeiro item da lista de code review.
