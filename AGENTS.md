# AGENTS.md

## Contexto

Agente de IA que responde perguntas em linguagem natural sobre `dataset/sales.csv`.
Desafio técnico; o enunciado original está em `README.pdf`.

**O plano de implementação (`IMPLEMENTATION_PLAN.md`) é a fonte de verdade** para
arquitetura, fases, escopo e critérios de aceite. Antes de propor mudança estrutural,
leia-o. Divergir dele exige justificativa escrita.

## Stack

Python 3.11+ · LangGraph (orquestração do agente) · LangChain (`langchain-core`,
`langchain-openai`) · FastAPI · DuckDB (motor analítico) · SQLGlot (validação de AST)
· Pydantic · Pytest · Ruff + Mypy · Docker.

Sem Pandas. Sem RAG. Sem `create_csv_agent` / `create_pandas_dataframe_agent`.

## Princípio central

**O LLM interpreta e narra. O DuckDB calcula.** Nenhum número que aparece numa
resposta ao usuário pode ter saído da inferência do modelo — todo valor vem de uma
query executada e visível no trace.

## Fatos do dataset (verificados — não suponha)

Colunas reais, nesta ordem, separador `;`:

```
product_id;local;date;planned_quantity;actual_quantity;planned_price;promotion_type;actual_price;service_level
```

São `product_id` e `local` — **não** `product` nem `location`.

- 203.635 linhas, período 2012-01-01 a 2012-12-31, zero nulos.
- `promotion_type` tem 2 valores: `'None'` (203.623 linhas, **string literal, não NULL**)
  e `'Flash'` (12 linhas, 2 produtos). `IS NOT NULL` não filtra promoções.
- `service_level` é constante `0.98` em 100% das linhas.
- `actual_price` difere de `planned_price` em exatamente as 12 linhas de promoção (-20%).
- 1.297 grupos de linhas duplicadas; não existe chave única.

Ground truth (deve bater exatamente):

| Query | Valor |
|---|---|
| Top produto por `actual_quantity` | `Product_1359` / 95.112.506 |
| Top local por `actual_quantity` | `Whse_J` / 617.421.620 |
| `SUM(actual_quantity)` | 953.555.461 |
| `SUM(planned_quantity)` | 949.259.991 |
| Diferença | 4.295.470 |

## Comandos

```bash
ruff check . && ruff format --check .
mypy app
pytest                      # sem rede; testes de integração ficam fora por padrão
uvicorn app.main:app --reload
python evals/run_evals.py    # consome tokens; não roda no CI
```

## Divisão dos arquivos de instrução

Para não haver três fontes de verdade em conflito:

- `IMPLEMENTATION_PLAN.md` — arquitetura, fases, escopo e critérios de aceite. Manda.
- `CLAUDE.md` — convenções de desenvolvimento e workflow por fase.
- `AGENTS.md` (este) — fatos verificados do dataset e regras de code review.

---

## Code Review Rules

Prioridade máxima aos itens de segurança e correção abaixo. Eles refletem os riscos
reais deste projeto, não preferências de estilo.

### Segurança — bloqueia merge

1. **Nenhum Python gerado pelo LLM é executado.** Sinalize qualquer `exec`, `eval`,
   `PythonAstREPLTool`, `create_csv_agent`, `create_pandas_dataframe_agent` ou
   `allow_dangerous_code=True`. O projeto existe para não tomar esse atalho.
2. **Todo SQL vindo do modelo passa por `validate_sql` antes de executar.** Sinalize
   qualquer caminho que chegue ao DuckDB sem passar pelo guard.
3. **O guard valida por AST, não por string.** Sinalize validação por regex, `.upper()`
   com busca de palavra-chave, ou allowlist textual — comentários, aliases e
   multi-statement escapam disso.
4. **Nenhum secret em código, log ou resposta de erro.** `OPENAI_API_KEY` é `SecretStr`;
   sinalize `.get_secret_value()` em contexto de log ou serialização.
5. **Corpo de resposta 5xx nunca contém stack trace** nem caminho de arquivo interno.

### Correção — alta prioridade

6. **Números vindos do LLM.** Sinalize qualquer valor numérico apresentado ao usuário
   que não tenha origem rastreável numa query executada.
7. **Nomes de coluna errados.** `product`/`location` em vez de `product_id`/`local`
   quebra em runtime — o schema é validado só no startup.
8. **`promotion_type` tratado como NULL.** `IS NULL` / `IS NOT NULL` nessa coluna é bug:
   o valor é a string `'None'`.
9. **Loop de agente sem cota de turnos.** O grafo precisa das duas travas: contador no
   estado e `recursion_limit`.
10. **Erro de ferramenta escapando como exceção.** `SQLValidationError` e
    `QueryExecutionError` dentro do nó de tools devem virar `ToolMessage` de volta ao
    modelo, não subir para o usuário — é isso que faz o self-correction funcionar.
11. **Concorrência do DuckDB.** Cada request usa `conn.cursor()`; sinalize uso
    compartilhado da conexão entre threads.
12. **Recurso instanciado em import de módulo** (conexão, client, `Settings()` no
    top-level).
13. **`except Exception: pass`** ou captura larga que engole erro de domínio.

### Testes

14. Sinalize teste removido, `skip` adicionado ou asserção enfraquecida para fazer o
    build passar.
15. Testes não podem depender de rede nem de `OPENAI_API_KEY`. O modelo é fake/mock.
16. Os valores de ground truth acima não mudam. Se um teste os altera, é o código que
    está errado.

### Fora de escopo do review

Não comente estilo, formatação, ordem de import ou nomes de variável — `ruff format`
resolve. Não sugira adicionar Pandas, RAG, cache distribuído, auth ou observabilidade
externa: são recusas deliberadas, documentadas em `docs/adr/`.
