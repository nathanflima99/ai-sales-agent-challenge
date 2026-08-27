# ADR 0003 — Validação de SQL por AST, com SQLGlot

## Contexto

O SQL executado contra o dataset é escrito por um modelo de linguagem. Ele precisa
ser tratado como entrada hostil: não porque o modelo seja malicioso, mas porque o
texto da pergunta do usuário influencia o que ele escreve.

## Decisão

Todo SQL passa por `validate_sql` antes de tocar o DuckDB. A validação parseia a
consulta com SQLGlot e a julga pelo **tipo dos nós da árvore**.

## Consequências

**Positivas**

- Julga o SQL pelo que ele é, não pelo que parece. `dRoP TaBlE sales` e
  `SELECT 1; -- comentário\nDROP TABLE sales;` são bloqueados sem nenhum
  tratamento especial.
- As mensagens de erro são escritas para o **modelo** ler, porque voltam como
  `ToolMessage` no self-correction. `"Table 'x' is not accessible; only 'sales'
  is available"` faz o modelo acertar no turno seguinte; `"invalid query"` custa
  um turno de tentativa e erro.
- O `LIMIT` é injetado quando ausente e **reduzido** quando alto demais. Um
  `LIMIT 500000` cabe na resposta da ferramenta, mas não no contexto do modelo.

**Negativas**

- Depende da fidelidade do parser do SQLGlot ao dialeto DuckDB. Uma sintaxe que o
  SQLGlot parseie diferente do DuckDB é um falso negativo em potencial.
- Consultas legítimas e exóticas podem ser rejeitadas. Preferimos esse lado do
  erro, e o self-correction absorve o custo.

## O que a evidência mudou no desenho

O plano original previa duas regras que **não funcionam** no SQLGlot 30, e ambas
só apareceram porque o parser foi testado antes de o guard ser escrito:

1. `exp.Command` **não** cobre `PRAGMA`/`COPY`/`INSTALL`. Cada um é um tipo de nó
   próprio (`Pragma`, `Copy`, `Install`, `Attach`).
2. Mais grave: aceitar apenas statements `SELECT` **não** impede leitura de
   arquivo arbitrário do disco.

```sql
SELECT * FROM read_csv_auto('C:/Windows/win.ini')
```

A raiz disso é um `Select` legítimo. O alvo não é uma tabela nomeada, é uma
*função de tabela*. Daí a lista explícita de funções de leitura proibidas
(`read_csv_auto`, `read_parquet`, `glob`, `read_text`, …).

## Segunda linha de defesa

Toda referência de tabela precisa ser `sales` ou um CTE local. Uma função de
tabela aparece na árvore como uma tabela **sem nome**, então mesmo que uma função
nova escape da lista de proibidas, ela é barrada aqui. As duas camadas cobrem
falhas uma da outra.

## Alternativas rejeitadas

**Regex ou allowlist de palavras** — comentários, caixa, aliases e statements
encadeadas escapam. É a abordagem que aparenta segurança sem entregá-la.

**Confiar só no modo read-only do DuckDB** — impediria escrita, mas não impediria
`read_csv_auto` de ler qualquer arquivo do container. Defesa em profundidade
precisa das duas.
