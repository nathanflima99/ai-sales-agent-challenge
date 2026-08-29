# AI Sales Agent Challenge — Plano de Implementação

> **v2 — corrigido contra o dataset real e o enunciado oficial (`ENUNCIADO.pdf`).**
> Todos os fatos de dataset abaixo foram verificados executando SQL no DuckDB 1.5.5
> sobre `dataset/sales.csv`. Nada aqui é suposição.

## Objetivo

Aplicação Python que responde perguntas em linguagem natural sobre `sales.csv`, usando **LangGraph** para orquestrar o ciclo de raciocínio do agente e **DuckDB** para calcular todos os resultados de forma determinística.

Entrega: repositório público no GitHub, com README, Dockerfile e testes.

**Prazo: 28/08 às 18h.**

---

## O que o enunciado pede (checklist literal)

Do `ENUNCIADO.pdf` do desafio:

| # | Requisito | Onde é atendido |
|---|---|---|
| 1 | Ler o arquivo `sales.csv` | Fase 2 — DuckDB view |
| 2 | Permitir que o usuário faça perguntas | Fase 6 — `POST /ask` + UI |
| 3 | **Utilizar uma biblioteca de agentes de IA (como LangChain ou LlamaIndex)** | Fase 4/5 — LangChain + LangGraph |
| 4 | Perguntas com cálculos e comparações entre colunas | Fase 5 prompt + Fase 7 evals |
| 5 | Over-engineering bem-vindo | SQL guard, self-correction, evals, ADRs |
| 6 | Dockerfile | Fase 8 |
| 7 | Preparar-se para discutir escolhas | ADRs + seção de perguntas |
| — | Instruções de uso e dependências no README | Fase 8 |

As **cinco perguntas de exemplo do enunciado** são o núcleo do golden set (Fase 7):

1. Qual produto foi mais vendido?
2. Qual local teve maior volume de vendas?
3. Qual foi o total de vendas em determinado período?
4. Qual a diferença entre quantidade planejada e realizada?
5. Qual o impacto das promoções no preço e volume vendido?

---

## Perfil real do dataset (verificado)

**Colunas exatas, nesta ordem** (separador `;`, arquivo com BOM UTF-8 que o DuckDB remove sozinho):

```text
product_id;local;date;planned_quantity;actual_quantity;planned_price;promotion_type;actual_price;service_level
```

| Coluna | Tipo inferido | Observação |
|---|---|---|
| `product_id` | VARCHAR | 1.966 valores distintos (`Product_0001`…) |
| `local` | VARCHAR | 4 armazéns: `Whse_J`, `Whse_A`, `Whse_S`, `Whse_C` |
| `date` | DATE | `DD/MM/YYYY` no CSV; inferido corretamente |
| `planned_quantity` | BIGINT | |
| `actual_quantity` | BIGINT | |
| `planned_price` | BIGINT | |
| `promotion_type` | VARCHAR | **apenas 2 valores: `'None'` (203.623) e `'Flash'` (12)** |
| `actual_price` | DOUBLE | |
| `service_level` | DOUBLE | **constante 0.98 em 100% das linhas** |

Fatos verificados:

- **203.635 linhas**, período **2012-01-01 a 2012-12-31** (um único ano).
- **Zero nulos** em qualquer coluna.
- `promotion_type` não tem NULL — tem a **string literal `'None'`**.
- `actual_price <> planned_price` em **exatamente 12 linhas — as mesmas 12 promoções**. Fora de promoção o preço praticado é sempre o planejado.
- As 12 linhas `Flash` cobrem **2 produtos**: `Product_0001` (Whse_J, 7 linhas) e `Product_0002` (Whse_C, 5 linhas). Desconto de **exatamente -20%** nos dois casos (136 → 108,8 e 212 → 169,6).
- **1.297 grupos de linhas exatamente duplicadas**; não existe chave única.
- Concentração: `Whse_J` tem 150.013 das 203.635 linhas (74%).
- Receita total (`SUM(actual_quantity * actual_price)`): **154.354.899.659,20**.

### Ground truth (valores conferidos)

| Query | Resultado |
|---|---|
| Produto de maior `actual_quantity` | `Product_1359` / **95.112.506** |
| Local de maior `actual_quantity` | `Whse_J` / **617.421.620** |
| `SUM(actual_quantity)` | **953.555.461** |
| `SUM(planned_quantity)` | **949.259.991** |
| Diferença (realizado − planejado) | **+4.295.470** |

---

## Princípios

1. **LLM interpreta e narra. DuckDB calcula.** Nenhum número relevante sai da inferência do modelo.
2. O CSV nunca é enviado integralmente ao modelo.
3. Todo SQL gerado pelo LLM passa por validação de AST antes de executar.
4. Apenas leitura, apenas a tabela `sales`.
5. **Nenhuma execução de Python arbitrário vindo do modelo.** Isso exclui deliberadamente os agentes prontos de CSV/Pandas do LangChain (ver ADR 0005).
6. Falhas de ferramenta voltam para o modelo corrigir, não para o usuário como stack trace.
7. Ambiguidade é declarada explicitamente, nunca resolvida em silêncio.
8. Causalidade não é afirmada a partir de amostra pequena — mas **o que é mensurável é respondido**.
9. A aplicação sobe e responde `/health` mesmo sem `OPENAI_API_KEY`.
10. Toda decisão arquitetural relevante vira um ADR.

---

## Stack

| Tecnologia | Papel |
|---|---|
| Python 3.11+ | Linguagem |
| **LangGraph** | Orquestração do loop do agente (grafo com estado) |
| **LangChain** (`langchain-core`, `langchain-openai`) | Abstração de modelo, `@tool`, tipos de mensagem |
| FastAPI + Uvicorn | API HTTP |
| DuckDB | Motor analítico sobre o CSV |
| SQLGlot | Validação de AST do SQL |
| Pydantic + pydantic-settings | Schemas e configuração |
| Pytest | Testes |
| Ruff + Mypy | Lint, formatação e tipagem |
| Docker | Empacotamento |

**Sem Pandas. Sem RAG. Sem `create_csv_agent` / `create_pandas_dataframe_agent`.** Justificativas nos ADRs.

> **Por que LangGraph e não só LangChain:** o enunciado pede uma biblioteca de agentes. LangChain sozinho dá o modelo e as tools; quem orquestra o ciclo `pensar → agir → observar → replanejar` com estado explícito e cota de turnos é o LangGraph. É a peça que transforma isto num agente em vez de um tradutor texto→SQL.
>
> **Por que `StateGraph` e não `create_react_agent`:** o prebuilt resolve o loop em uma linha, mas esconde exatamente o que preciso expor — o trace de cada tool call, a cota de turnos e o tratamento de erro de ferramenta. Construo o grafo com dois nós para que essas três coisas sejam código meu e visíveis na resposta. É a diferença entre usar a lib e saber o que ela faz. (ADR 0002.)

---

## Arquitetura

```text
                        ┌─────────────────────────────┐
Usuário  ──HTTP──▶      │  FastAPI                    │
(curl / UI)             │  /health  /ask              │
                        │  middleware: request_id, log│
                        └──────────────┬──────────────┘
                                       ▼
                        ┌─────────────────────────────┐
                        │  LangGraph StateGraph       │
                        │                             │
                        │   ┌────────┐  tool_calls    │
                        │   │ agent  │────────────┐   │
                        │   │ (LLM)  │◀───────┐   │   │
                        │   └───┬────┘        │   ▼   │
                        │       │        ┌────┴─────┐ │
                        │  submit_answer │  tools   │ │
                        │       │        └────┬─────┘ │
                        │       ▼             │       │
                        │     [END]           │       │
                        └─────────────────────┼───────┘
                                              ▼
                   ┌──────────────────────────────────────┐
                   │ Tools (@tool)                        │
                   │ • query_sales_data                   │
                   │ • inspect_column                     │
                   │ • submit_answer  (nó terminal)       │
                   └──────────────┬───────────────────────┘
                                  ▼
                        ┌──────────────────┐
                        │ SQL Guard        │
                        │ (SQLGlot AST)    │
                        └────────┬─────────┘
                                 ▼
                        ┌──────────────────┐
                        │ AnalyticsRepo    │
                        │ DuckDB + cache   │
                        └────────┬─────────┘
                                 ▼
                            sales.csv (view)
```

**Componentes**

- **FastAPI** — expõe `/health` e `/ask`. Middleware injeta `request_id` e mede latência.
- **AgentGraph (LangGraph)** — `StateGraph` com estado `{messages, turns}`. Nó `agent` chama o LLM; aresta condicional roteia para `tools` ou para `END`. Erro de ferramenta vira `ToolMessage` de volta ao modelo (self-correction). `recursion_limit` + contador de turnos no estado impedem loop infinito.
- **Modelo** — `ChatOpenAI` do `langchain-openai`, instanciado no `lifespan` com timeout e retries, `bind_tools()` aplicado uma vez. Trocar de provider = trocar por outro `BaseChatModel`; a abstração já vem da lib.
- **Tools** — três, decoradas com `@tool` e args em Pydantic. `submit_answer` é a única saída do grafo, o que garante `answer`/`assumptions`/`warnings` estruturados.
- **SQL Guard** — valida a AST via SQLGlot, bloqueia tudo que não for `SELECT`/`WITH` sobre `sales` e injeta `LIMIT`.
- **AnalyticsRepository** — DuckDB em memória com `sales.csv` registrado como view; `cursor()` por request; cache de resultados por hash do SQL.

---

## Estrutura de pastas

```text
ai-sales-agent-challenge/
├── app/
│   ├── __init__.py
│   ├── main.py                # app factory, lifespan, exception handlers
│   ├── config.py              # Settings
│   ├── schemas.py             # AskRequest, AskResponse, ToolTrace
│   ├── errors.py              # exceções de domínio
│   ├── logging_setup.py       # logging JSON + contextvars
│   ├── api/
│   │   ├── routes.py
│   │   └── middleware.py
│   ├── agent/
│   │   ├── graph.py           # StateGraph, nós e arestas
│   │   ├── state.py           # AgentState (TypedDict)
│   │   ├── prompts.py
│   │   ├── tools.py           # @tool x3
│   │   └── model.py           # factory do ChatOpenAI
│   └── analytics/
│       ├── repository.py
│       ├── profiling.py
│       └── sql_guard.py
├── dataset/sales.csv
├── evals/
│   ├── golden_questions.yaml
│   └── run_evals.py
├── tests/
│   ├── conftest.py
│   ├── fixtures/sample_sales.csv
│   ├── test_ground_truth.py
│   ├── test_sql_guard.py
│   ├── test_agent.py
│   └── test_api.py
├── docs/adr/
├── static/index.html          # ESSENCIAL, não extra
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── ENUNCIADO.pdf              # enunciado original, mantido para contexto
└── README.md
```

---

## Convenções de código (valem para todas as fases)

- Type hints em toda função pública. `mypy` em modo básico deve passar.
- `ruff check` e `ruff format` devem passar antes de cada commit.
- Configuração só via `Settings` injetada — nenhum `os.getenv()` espalhado.
- `OPENAI_API_KEY` como `SecretStr | None`.
- Nenhum recurso (conexão, client) instanciado em import de módulo — tudo no `lifespan`.
- Nenhum `except Exception: pass`. Exceções de domínio herdam de `AppError` e são mapeadas por `@app.exception_handler`.
- Corpo de erro 5xx nunca contém stack trace.
- **Dependências pinadas em versão exata** — build de amanhã tem que dar o mesmo resultado do de hoje.
- Nada de secret no Git.

---

# Fase 1 — Fundação

**Prioridade: Essencial · Estimativa: 1h**

### Objetivo
Esqueleto do projeto com configuração, erros, logging e `/health` funcionando.

### O que implementar

`pyproject.toml` com dependências **pinadas** e config de ruff/mypy/pytest (incluindo `markers = ["integration"]` e `addopts = "-m 'not integration'"`).

`app/config.py`:
```python
class Settings(BaseSettings):
    openai_api_key: SecretStr | None = None   # opcional: /health sobe sem chave
    openai_model: str = "gpt-4o-mini"
    dataset_path: Path = Path("dataset/sales.csv")
    max_query_rows: int = 100
    max_agent_turns: int = 6
    llm_timeout_seconds: int = 30
    log_level: str = "INFO"
    model_config = SettingsConfigDict(env_file=".env")
```

> **`openai_api_key` é opcional de propósito.** Com `SecretStr` obrigatório, o app quebra no import e o avaliador que rodar `docker run` sem chave vê um stack trace em vez da aplicação. Sem chave: `/health` responde `{"status":"ok","llm":"unconfigured"}`, a UI carrega, e só o `/ask` devolve 503 com mensagem explicando como configurar.

`app/errors.py`:
```python
class AppError(Exception):
    status_code = 500
class DatasetError(AppError): status_code = 500
class SQLValidationError(AppError): status_code = 400
class QueryExecutionError(AppError): status_code = 400
class LLMError(AppError): status_code = 503
class LLMNotConfiguredError(LLMError): status_code = 503
class AgentLoopError(AppError): status_code = 500
```

`app/logging_setup.py` — formatter JSON, `request_id` em `contextvars`.

`app/main.py` — app factory, `lifespan` (vazio por enquanto), `exception_handler(AppError)`, rota `GET /health`.

`.env.example`, `.gitignore`, `.dockerignore`.

### Critério de aceite
```bash
uvicorn app.main:app --reload
curl localhost:8000/health   # {"status":"ok", ...}  — sem OPENAI_API_KEY definida
ruff check . && mypy app     # sem erros
```

### Commit
```text
chore: bootstrap project with config, errors and structured logging
```

---

# Fase 2 — Camada analítica (DuckDB)

**Prioridade: Essencial · Estimativa: 1h30**

### Objetivo
Consultar `sales.csv` via DuckDB, com profile do dataset calculado no startup. Sem IA envolvida.

### O que implementar

`app/analytics/repository.py`:
- Conexão DuckDB em memória, aberta no `lifespan`.
- View: `CREATE VIEW sales AS SELECT * FROM read_csv_auto('<path>', delim=';')`.
- **`conn.cursor()` por request.** A conexão DuckDB não é thread-safe para uso simultâneo e o FastAPI roda handlers sync em threadpool.
- `execute_query(sql: str) -> QueryResult` devolvendo `rows`, `row_count`, `elapsed_ms`, `cache_hit`.
- Cache LRU por hash do SQL.

`app/analytics/profiling.py`:
- `build_profile(conn) -> DatasetProfile` via SQL puro.
- `validate_schema(conn)` — se faltar coluna obrigatória, levanta `DatasetError` **no startup**, nomeando a coluna ausente.

**Colunas obrigatórias (nomes reais, confirmados no CSV):**
```python
REQUIRED_COLUMNS = [
    "product_id", "local", "date",
    "planned_quantity", "actual_quantity",
    "planned_price", "promotion_type",
    "actual_price", "service_level",
]
```

> ⚠️ **Correção importante.** A v1 deste plano listava `product` e `location`. Os nomes reais são `product_id` e `local`, e `promotion_type` vem **antes** de `actual_price`. Um `validate_schema` com os nomes antigos falharia no startup.

### Pontos de atenção verificados

- **Datas:** o CSV usa `DD/MM/YYYY`. O `read_csv_auto` infere `DATE` corretamente (confirmado: 121.097 linhas têm dia > 12, o que força a interpretação certa). Ainda assim, escreva um teste que asserte `MIN(date) = 2012-01-01` e `MAX(date) = 2012-12-31` — se uma versão futura do DuckDB mudar a heurística, o teste pega.
- **BOM:** o arquivo começa com BOM UTF-8. O DuckDB 1.5.5 o remove e a coluna sai como `product_id` limpa. Teste que asserta o nome exato da primeira coluna trava esse comportamento.
- **Tipos:** todos inferidos corretamente, sem separador de milhar ou decimal pt-BR. Não é preciso `CAST` explícito.

### Critério de aceite
As queries de ground truth retornam exatamente os valores da tabela de ground truth acima. App falha no startup, com mensagem clara, se o CSV não existir ou faltar coluna.

### Testes
`tests/test_ground_truth.py`: os 4 valores + a diferença (`4.295.470`) + `COUNT(*) = 203635` + nomes de colunas + range de datas.

### Commit
```text
feat: add DuckDB analytics repository and dataset profiling
```

### Perguntas de entrevista
- Por que DuckDB em vez de Pandas?
- Qual o risco de concorrência aqui e como você tratou?
- Como isso escalaria para um arquivo de 200 GB no S3?

---

# Fase 3 — SQL Guard

**Prioridade: Essencial · Estimativa: 1h**

### Objetivo
Garantir que nenhum SQL vindo do modelo faça algo além de ler a tabela `sales`.

### O que implementar

`app/analytics/sql_guard.py` — `validate_sql(sql: str, max_rows: int) -> str`:

1. `sqlglot.parse(sql, dialect="duckdb")`.
2. Rejeita se houver mais de uma statement.
3. Rejeita se a raiz não for `exp.Select` ou `exp.With`.
4. Percorre a AST e rejeita nós de `Drop`, `Insert`, `Update`, `Delete`, `Alter`, `Create`, `Attach`, `Command` (esse último cobre `PRAGMA`, `COPY`, `INSTALL`, `LOAD`, `CALL` e demais comandos DuckDB fora do SQL padrão).
5. Rejeita se qualquer tabela referenciada não for `sales`.
6. Injeta `LIMIT max_rows` se não houver `LIMIT`.
7. Devolve o SQL normalizado.

**Mensagens de erro devem ser legíveis pelo modelo** — elas voltam para o LLM como `ToolMessage` no self-correction da Fase 5. Ex.: `"Only SELECT statements are allowed"`, `"Table 'x' is not accessible; only 'sales' is available"`.

### Por que isso existe
Bloquear por regex é frágil: comentários, case, aliases e statements encadeadas escapam. Validar por **tipo de nó da AST** é robusto e cabe em pouco código.

### Critério de aceite / Testes
`tests/test_sql_guard.py`:

```text
SELECT * FROM sales LIMIT 10             → permitido
SELECT product_id FROM sales             → permitido, LIMIT injetado
WITH t AS (SELECT ...) SELECT * FROM t   → permitido
SELECT * FROM sales; DROP TABLE sales;   → bloqueado (multi-statement)
DROP TABLE sales                         → bloqueado
DELETE FROM sales                        → bloqueado
INSERT INTO sales VALUES (...)           → bloqueado
PRAGMA database_list                     → bloqueado
COPY sales TO '/tmp/x.csv'               → bloqueado
SELECT * FROM outra_tabela               → bloqueado (tabela não autorizada)
SELEC * FROM sales                       → bloqueado (SQL inválido)
```

### Commit
```text
feat: add AST-based read-only SQL validation
```

### Perguntas de entrevista
- Por que SQLGlot e não regex ou allowlist de palavras?
- Que ataque ainda seria possível se o guard tivesse um bug?
- Por que não confiar apenas no modo read-only do DuckDB?

---

# Fase 4 — Modelo e ferramentas (LangChain)

**Prioridade: Essencial · Estimativa: 1h15**

### Objetivo
Configurar o `ChatOpenAI` e expor as três ferramentas do agente como `@tool` do LangChain.

### O que implementar

`app/agent/model.py`:
```python
def build_model(settings: Settings) -> BaseChatModel:
    if settings.openai_api_key is None:
        raise LLMNotConfiguredError("OPENAI_API_KEY is not set")
    return ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
        temperature=0,
    )
```
Instanciado no `lifespan`, **injetado** no grafo — nunca criado dentro de um nó.

O tipo de retorno é `BaseChatModel`, não `ChatOpenAI`: a abstração de provider já vem do LangChain, então não escrevo um `Protocol` meu para isso. Trocar para `ChatAnthropic` é trocar a factory.

`app/agent/tools.py` — três tools com `@tool` e schemas Pydantic:

**1. `query_sales_data(sql: str)`** → `validate_sql` → `execute_query` → resultado estruturado.

**2. `inspect_column(column: str)`** → `{"distinct_count", "sample_values", "dtype"}`.

> `inspect_column` resolve uma classe concreta de alucinação **que este dataset provoca**: `promotion_type` não tem NULL, tem a string literal `'None'`. Sem inspecionar, o modelo escreve `WHERE promotion_type IS NOT NULL` e recebe as 203.635 linhas achando que filtrou promoções. Cinto e suspensório: o valor também vai explícito no system prompt.

**3. `submit_answer(answer: str, assumptions: list[str], warnings: list[str])`** → nó terminal do grafo.

> **Esta tool fecha um furo da v1 do plano.** A v1 declarava `assumptions` e `warnings` no `AskResponse` mas nunca dizia como o modelo os produzia — o `_finalize` era implícito. Sem uma saída estruturada, esses campos ficam vazios e os evals de comportamento não têm o que asseverar. Fazendo de `submit_answer` a **única** aresta para `END`, o contrato fica garantido pelo grafo: ou o modelo chama uma tool de dados, ou ele encerra com resposta estruturada.

Schema e perfil do dataset **não** são tools: são estáticos e cabem no system prompt. Tool serve para o que é dinâmico.

### Critério de aceite
`query_sales_data.invoke({"sql": "SELECT ..."})` retorna resultado correto; SQL destrutivo levanta `SQLValidationError`.

### Commit
```text
feat: add LangChain model factory and agent tools
```

### Perguntas de entrevista
- Por que três tools e não cinco? Por que o schema não é tool?
- Por que `submit_answer` em vez de structured output no último turno?
- Como você trocaria de provider?

---

# Fase 5 — Agente LangGraph com self-correction

**Prioridade: Essencial · Estimativa: 1h30**

### Objetivo
Transformar a pergunta em tool calls e depois em resposta estruturada, recuperando de falhas de ferramenta.

### O que implementar

`app/agent/state.py`:
```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    turns: int
    trace: list[ToolTrace]
    final: FinalAnswer | None
```

`app/agent/graph.py`:
```python
def build_graph(model: BaseChatModel, profile: DatasetProfile,
                settings: Settings) -> CompiledGraph:
    bound = model.bind_tools([query_sales_data, inspect_column, submit_answer])

    def agent_node(state: AgentState) -> dict:
        if state["turns"] >= settings.max_agent_turns:
            raise AgentLoopError("Max agent turns exceeded")
        response = bound.invoke(state["messages"])
        return {"messages": [response], "turns": state["turns"] + 1}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if not last.tool_calls:
            return "agent"                    # força uso de submit_answer
        if last.tool_calls[0]["name"] == "submit_answer":
            return "finish"
        return "tools"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)       # captura erro → ToolMessage
    graph.add_node("finish", finish_node)     # extrai FinalAnswer + trace
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", route,
                                {"tools": "tools", "finish": "finish",
                                 "agent": "agent"})
    graph.add_edge("tools", "agent")
    graph.add_edge("finish", END)
    return graph.compile()
```

O `tools_node` **não deixa exceção escapar**: `SQLValidationError` e `QueryExecutionError` viram `ToolMessage` com `{"error": ..., "hint": "Fix the query and call the tool again."}` e o grafo volta para `agent`. É isso que torna o sistema um agente e não um tradutor texto→SQL: ele observa o resultado da própria ação, detecta falha e replaneja.

Duas travas contra loop infinito, de propósito: o contador `turns` no estado (erro de domínio controlado, com mensagem) e o `recursion_limit` do LangGraph (rede de segurança da lib).

`app/agent/prompts.py` — system prompt montado com o `DatasetProfile` da Fase 2:

- papel: analista de dados sobre um dataset de vendas;
- descrição semântica de cada coluna, **com os nomes reais** (`product_id`, `local`);
- perfil do dataset: 203.635 linhas, 1.966 produtos, 4 armazéns, período 2012-01-01 a 2012-12-31, zero nulos;
- **avisos de armadilha do dataset**, explícitos:
  - `promotion_type` tem só dois valores, `'None'` (string literal, **não** NULL) e `'Flash'`; promoções são **12 linhas**, em **2 produtos**;
  - `service_level` é constante 0.98 — não há variação a analisar;
  - `actual_price` só difere de `planned_price` nessas mesmas 12 linhas;
- regra: **nunca calcular números de cabeça** — sempre gerar SQL e usar a tool;
- regra de ambiguidade: "total de vendas" admite quantidade (953.555.461 un.) ou receita (R$ 154,35 bi). Escolher uma, **declarar em `assumptions`**, e mencionar a alternativa;
- regra de causalidade e de escopo amostral — detalhada abaixo;
- regra de encerramento: sempre finalizar com `submit_answer`;
- few-shot curto ilustrando os comportamentos acima.

### Regra de promoções — corrigida

> A v1 mandava "nunca afirmar que promoção causou variação de volume" e o eval esperava `refuses_causality`. Isso é meio caminho: **"Qual o impacto das promoções no preço e volume vendido?" é uma das cinco perguntas do enunciado.** Recusar as duas metades responde mal ao desafio.

O comportamento correto separa o que é mensurável do que não é:

- **Preço — responder com precisão.** O desconto é determinístico e verificável: `Product_0001` 136 → 108,8 e `Product_0002` 212 → 169,6, **-20% exatos nos dois casos**. Fora dessas 12 linhas, preço praticado = preço planejado.
- **Volume — delimitar.** 12 registros, 2 produtos, 1 ano. Não há grupo de controle nem variação temporal suficiente. Reportar os números observados, e usar `warnings` para dizer que a amostra não sustenta atribuição causal.

Ou seja: `answer` traz o achado de preço, `warnings` traz a limitação de volume. Responder a parte respondível e delimitar a outra vale mais que uma recusa.

### Critério de aceite
"Qual produto foi mais vendido?" retorna `Product_1359` / 95.112.506 via tool call real. Um SQL propositalmente errado no primeiro turno é corrigido no segundo.

### Testes
`tests/test_agent.py`, com modelo **fake** (sem rede, sem tokens) — `FakeMessagesListChatModel` do `langchain_core.language_models.fake_chat_models`, ou um `BaseChatModel` próprio que devolve `AIMessage` com `tool_calls` pré-programados:
1. fluxo feliz: uma tool call → `submit_answer`;
2. self-correction: primeira tool falha (SQL inválido), segunda acerta;
3. estouro de turnos levanta `AgentLoopError`.

### Commit
```text
feat: implement LangGraph agent with tool self-correction
```

### Perguntas de entrevista
- O que torna isso um agente e não um wrapper de prompt?
- Por que `StateGraph` e não `create_react_agent`?
- O grafo pode ficar infinito? Como você impediu — e por que duas travas?
- Por que ambiguidade virou regra de prompt e não código?
- E se o modelo gerar SQL válido mas semanticamente errado? Como detectar?

---

# Fase 6 — API, UI e observabilidade

**Prioridade: Essencial · Estimativa: 1h30**

### Objetivo
Expor o agente por HTTP com contrato estruturado, erros tratados e uma interface que o avaliador consegue abrir.

### O que implementar

`app/schemas.py`:
```python
class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

class ToolTrace(BaseModel):
    name: str
    args: dict
    status: Literal["ok", "error"]
    elapsed_ms: float | None = None
    error: str | None = None

class AskResponse(BaseModel):
    answer: str
    assumptions: list[str] = []
    warnings: list[str] = []
    metadata: dict   # trace, turns, tokens_used, total_ms, cache_hit
```

`app/api/routes.py` — `POST /ask`, `GET /health`.

`app/api/middleware.py` — gera `request_id`, mede duração, devolve header `X-Request-ID`.

**`static/index.html` — promovido de "extra" para essencial.** Input, botão, render da resposta e do trace (SQL gerado visível). Zero build step, zero dependência, servido por `StaticFiles`. É a primeira coisa que o avaliador abre e é o que atende diretamente ao "permita que o usuário faça perguntas sobre os dados". Deve mostrar um aviso claro se `/health` reportar `llm: unconfigured`.

Log estruturado por request: `request_id`, pergunta, cada SQL executado, latência de cada query, turnos, duração total, erro. Nunca logar a API key.

> **`/metrics` foi cortado.** Contadores p50/p95 em memória demonstram intenção, mas o trace por request já dá a observabilidade que importa para depurar um agente, e o tempo vale mais em outro lugar.

### Critério de aceite
```bash
curl -X POST localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Qual produto foi mais vendido?"}'
```
retorna `answer` correta, `metadata.trace` com o SQL visível, e `X-Request-ID` no header. `http://localhost:8000/` abre a UI.

### Testes
`tests/test_api.py`: `/health` sem chave; `/ask` feliz com grafo mockado; pergunta vazia → 422; falha de LLM → 503 sem stack trace no corpo.

### Commit
```text
feat: add /ask endpoint, static UI and execution trace
```

---

# Fase 7 — Evals

**Prioridade: Importante · Estimativa: 1h15**

### Objetivo
Medir a qualidade do agente de forma reproduzível, apesar do não determinismo.

### O que implementar

`evals/golden_questions.yaml` — **as cinco perguntas do enunciado primeiro**, depois os casos de comportamento:

```yaml
# --- as 5 perguntas do enunciado ---
- id: top_product              # enunciado #1
  question: "Qual produto foi mais vendido?"
  expects_value: "Product_1359"
  expects_number: 95112506

- id: top_location             # enunciado #2
  question: "Qual local teve maior volume de vendas?"
  expects_value: "Whse_J"
  expects_number: 617421620

- id: period_total             # enunciado #3
  question: "Qual foi o total de vendas no primeiro trimestre de 2012?"
  expects_sql_contains: ["date", "2012"]
  expects_behavior: filters_by_date

- id: plan_gap                 # enunciado #4
  question: "Qual a diferença entre quantidade planejada e realizada?"
  expects_number: 4295470

- id: promo_impact             # enunciado #5
  question: "Qual o impacto das promoções no preço e volume vendido?"
  expects_behavior: quantifies_price_and_caveats_volume

# --- comportamento ---
- id: ambiguous_sales
  question: "Qual foi o total de vendas?"
  expects_behavior: declares_assumption

- id: promo_null_trap
  question: "Quantas vendas tiveram promoção?"
  expects_number: 12

- id: out_of_scope
  question: "Qual a previsão de vendas para 2030?"
  expects_behavior: declines_gracefully
```

`evals/run_evals.py` — roda cada pergunta contra o agente real e aplica as assertions.

> **Correção de método.** A v1 checava `expects_number` como substring da resposta em texto. Isso quebra na formatação: o modelo escreve `95.112.506`, `95,112,506` ou "cerca de 95 milhões" e o eval falha com o agente certo. Duas mudanças:
>
> 1. Asserção primária sobre o **resultado da tool no trace**, não sobre a prosa. O número saiu do DuckDB; é ali que se verifica.
> 2. Asserção secundária sobre o texto com **normalização de dígitos** (remove `.`, `,`, espaços) para confirmar que o modelo narrou o número que a tool devolveu, em vez de inventar outro.
>
> Isso também responde melhor na entrevista: separa "o agente chegou ao dado certo" de "o agente narrou o dado certo", que são falhas diferentes.

Não roda no CI padrão (consome tokens). O resultado da última execução vai para o README.

### Critério de aceite
```bash
python evals/run_evals.py
```
imprime taxa de acerto; alvo ≥ 7/8.

### Commit
```text
test: add golden question eval harness
```

### Perguntas de entrevista
- Como você mediria regressão ao trocar de modelo?
- Por que golden set em vez de LLM-as-judge?
- Qual a diferença entre seus ground truth tests e seus evals?

---

# Fase 8 — Docker, ADRs e README

**Prioridade: Essencial · Estimativa: 2h30**

### Docker

`Dockerfile`: `python:3.11-slim`, usuário não-root, `pyproject`/lock copiados antes do código (cache de layer), `HEALTHCHECK` em `/health`, `CMD uvicorn app.main:app --host 0.0.0.0 --port 8000`.

`.dockerignore` incluindo `.git`, `.venv`, `__pycache__`, `.env`.

`docker-compose.yml` lendo `OPENAI_API_KEY` do ambiente.

Critério de aceite — **inclusive sem chave**:
```bash
docker build -t ai-sales-agent .
docker run --rm -p 8000:8000 ai-sales-agent           # sobe, /health ok, UI carrega
docker run --rm -p 8000:8000 -e OPENAI_API_KEY=... ai-sales-agent
curl localhost:8000/health
```

### ADRs

`docs/adr/`, formato Contexto / Decisão / Consequências / Alternativas rejeitadas. **Seis, bem escritos** (a v1 pedia oito; quatro rasos valem menos que quatro bons):

1. `0001-duckdb-over-pandas.md`
2. `0002-langgraph-stategraph-over-prebuilt.md` — por que LangGraph, e por que grafo próprio em vez de `create_react_agent`
3. `0003-sqlglot-ast-validation.md`
4. `0004-tools-vs-prompt.md` — critério de quando algo vira tool; por que `submit_answer` existe
5. `0005-no-pandas-csv-agent.md` — **o mais importante**
6. `0006-testing-a-nondeterministic-system.md`

> **ADR 0005 é o de maior valor na entrevista.** O caminho óbvio dentro do LangChain para "agente que analisa CSV" é `create_csv_agent` / `create_pandas_dataframe_agent`. Ambos funcionam executando **Python gerado pelo LLM** via `PythonAstREPLTool`. Isso significa `exec` de código de modelo no processo da aplicação — RCE por construção, com `allow_dangerous_code=True` exigido explicitamente pela própria lib. Escolhi o caminho mais longo: o LLM gera **SQL**, que passa por validação de AST e roda num motor somente-leitura com uma única tabela exposta. Usar a biblioteca sem usar o atalho inseguro dela, e saber explicar a diferença, é o ponto do ADR.

### README

1. O que o projeto faz (2-3 frases)
2. **Aviso no topo: precisa de `OPENAI_API_KEY` para o `/ask`; sem ela a app sobe e a UI carrega, mas não responde perguntas**
3. Arquitetura (diagrama acima)
4. Tecnologias e por quê (tabela)
5. Instalação local
6. Configuração (`.env`)
7. Execução local e via Docker
8. Como rodar testes e evals
9. Exemplos de perguntas e respostas — **as cinco do enunciado**
10. **Exemplo de trace completo** — JSON de `/ask` com o SQL gerado visível
11. Resultados dos evals
12. Decisões arquiteturais (resumo + link para ADRs)
13. Segurança — SQL guard, por que não `exec`, secret handling
14. Achados sobre os dados (promoções = 12 linhas, `service_level` constante, 1.297 duplicatas)
15. Limitações conhecidas e próximos passos

### Commits
```text
chore: add Dockerfile and compose setup
docs: add architecture decision records
docs: write README with usage, trace example and eval results
```

---

# Extras (só depois que tudo acima estiver funcionando)

1. **CI (GitHub Actions)** — `ruff` + `mypy` + `pytest`. Barato e visível no repo.
2. **Multi-turn** — `session_id` + `MemorySaver` do LangGraph (checkpointer nativo, poucas linhas). Permite follow-up ("e no ano anterior?"). Documentar que em produção seria Redis.
3. **Streaming** — `graph.astream_events()` via SSE, mostrando o agente pensando.
4. **Rate limiting** por IP.

> Multi-turn subiu de prioridade em relação à v1: com LangGraph é `MemorySaver` + `thread_id`, quase de graça, e é uma demonstração direta de por que a lib foi escolhida.

---

# Fora de escopo (documentado nos ADRs)

| Descartado | Motivo |
|---|---|
| `create_csv_agent` / `create_pandas_dataframe_agent` | Executam Python gerado pelo LLM (`exec`). RCE por construção. É o atalho que este projeto existe para não tomar. |
| Pandas | DuckDB cobre leitura, tipos, agregação e profiling. Duas camadas fazendo o mesmo é risco de divergência. |
| RAG / embeddings | As perguntas são agregações estruturadas; busca vetorial resolve outro problema. |
| Múltiplos agentes | Não há divisão de responsabilidade que justifique coordenação. |
| `/metrics` | O trace por request já cobre a depuração; tempo melhor gasto na UI. |
| Auth, K8s, banco externo | Fora do escopo; custo alto, sinal baixo. |

---

# Caminho crítico

| # | Etapa | Estimativa | Marco |
|---|---|---|---|
| 1 | Fundação | 1h | |
| 2 | Camada analítica + ground truth | 1h30 | |
| 3 | SQL Guard | 1h | |
| 4 | Modelo e tools | 1h15 | |
| 5 | Grafo LangGraph com self-correction | 1h30 | |
| 6 | API + UI | 1h30 | **PUSH 1 — entrega já válida** |
| 7 | Testes restantes (api, agent) | 1h | |
| 8 | Docker | 45min | **PUSH 2 — executável por terceiros** |
| 9 | Evals | 1h15 | |
| 10 | ADRs | 1h | |
| 11 | README | 45min | **PUSH 3 — entrega competitiva** |
| 12 | Extras | resto | PUSH 4 |
| — | Reserva para imprevistos | 2h | |

**Mudança de ordem em relação à v1:** Docker subiu para antes dos evals. "Roda na máquina do avaliador" é requisito explícito do enunciado; eval é diferencial. Nunca deixe o diferencial na frente do requisito.

**Regra de push:** primeiro push assim que o passo 6 estiver de pé. Nunca fique em estado quebrado esperando terminar a próxima feature.

**Se o tempo apertar, corte nesta ordem:** extras → evals → `inspect_column` → 2 dos 6 ADRs.
**Nunca corte:** ground truth tests, SQL guard, self-correction, UI, Docker, README, ADR 0005.

### MVP
Passos 1-6. API + UI respondendo perguntas reais, cálculo determinístico, SQL validado.

### Entrega forte
Passos 1-11.

---

# Definition of Done

- [ ] Repositório público, clonável
- [ ] `docker build` e `docker run` funcionam conforme o README, **inclusive sem `OPENAI_API_KEY`** (app sobe, `/ask` devolve 503 explicativo)
- [ ] `/health` responde
- [ ] UI em `/` permite perguntar e mostra o trace
- [ ] `/ask` aceita linguagem natural e devolve resposta estruturada com trace
- [ ] Usa biblioteca de agentes de IA (LangChain + LangGraph) — requisito #3 do enunciado
- [ ] Todo número da resposta vem do DuckDB, nenhum do LLM
- [ ] SQL validado por AST; destrutivos e multi-statement bloqueados
- [ ] Nenhum Python gerado pelo LLM é executado
- [ ] Falha de ferramenta é corrigida pelo agente, não devolvida como erro
- [ ] Grafo tem cota de turnos com erro controlado
- [ ] Os 5 valores de ground truth batem exatamente
- [ ] Nomes de coluna reais (`product_id`, `local`) em todo o código
- [ ] Ambiguidade declarada em `assumptions` via `submit_answer`
- [ ] Pergunta de promoções: quantifica o efeito no preço, delimita o de volume
- [ ] As 5 perguntas do enunciado respondidas e documentadas no README
- [ ] `pytest` passa sem rede
- [ ] `ruff` e `mypy` passam
- [ ] Evals executados e resultado no README
- [ ] Nenhum secret no Git
- [ ] 6 ADRs escritos

---

# Regras para o agente de desenvolvimento

1. Uma fase por vez; não adiante fases futuras.
2. Antes de desviar da arquitetura deste plano, justifique por escrito.
3. Rode `ruff`, `mypy` e os testes da fase após cada mudança relevante.
4. Não remova nem enfraqueça teste para fazer o build passar.
5. **Nunca execute Python vindo do LLM.** Não importe `PythonAstREPLTool` nem agentes de CSV/Pandas.
6. Nunca envie o CSV inteiro ao modelo.
7. Nenhum recurso instanciado em import de módulo.
8. Use os nomes reais das colunas: `product_id`, `local`.
9. Prefira código explícito e tipado a abstração genérica.
10. Cada commit representa uma mudança coerente e passa nos testes daquela fase.
11. Nunca commite `.env`, chaves ou tokens.
12. Atualize o README quando a forma de executar mudar.
13. Ao final de cada fase, resuma: arquivos alterados, decisão tomada, testes executados, resultado, próximo passo.

---

# Perguntas de entrevista a preparar

```text
O que torna esse sistema um agente e não um wrapper de prompt?
Onde está a fronteira entre raciocínio do LLM e cálculo determinístico?
Por que LangGraph e não LangChain puro? Por que StateGraph e não create_react_agent?
Por que você NÃO usou create_csv_agent / create_pandas_dataframe_agent?
Por que DuckDB e não Pandas?
Por que SQLGlot e não regex?
Por que três tools? Por que o schema não é tool? Por que submit_answer existe?
Seu grafo pode ficar infinito? Como você impediu — e por que duas travas?
O que acontece se o modelo gerar SQL válido mas semanticamente errado?
Como você testa um sistema não determinístico?
Qual a diferença entre seus ground truth tests e seus evals?
Como mediria regressão ao trocar de modelo?
Qual o risco de concorrência do DuckDB aqui?
O guard tem falso negativo conhecido? Qual a segunda linha de defesa?
Você achou 1.297 linhas duplicadas — são erro ou transações legítimas? Como decidiria?
Por que o dataset tem só 12 promoções? O que isso limita nas conclusões?
Como escalaria para 200 GB? Como trocaria CSV por Postgres/BigQuery?
Como levaria isso a produção multi-tenant?
Quais riscos existem ao permitir que IA produza SQL?
```
