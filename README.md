# AI Sales Agent

Agente de IA que responde perguntas em linguagem natural sobre `dataset/sales.csv`
(203.635 registros de vendas de 2012).

O princípio que organiza todo o projeto: **o modelo interpreta e narra; o DuckDB
calcula.** Nenhum número que aparece numa resposta sai da inferência do LLM — todos
vêm de uma consulta SQL que é validada antes de executar e fica visível no trace da
resposta.

---

## Começando em 30 segundos

```bash
git clone https://github.com/nathanflima99/ai-sales-agent-challenge.git
cd ai-sales-agent-challenge
docker build -t ai-sales-agent .
docker run --rm -p 8000:8000 ai-sales-agent
```

Abra <http://localhost:8000>. A aplicação sobe, carrega o dataset e serve a
interface **mesmo sem credencial de LLM** — `/health` responde e a UI avisa o que
falta. Para responder perguntas, escolha um provider abaixo.

### Com OpenAI

```bash
docker run --rm -p 8000:8000 -e OPENAI_API_KEY=sk-... ai-sales-agent
```

### Com Ollama (local, sem chave e sem custo)

```bash
ollama pull qwen3.5:4b
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=ollama \
  -e LLM_MODEL=qwen3.5:4b \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  ai-sales-agent
```

> O modelo Ollama **precisa suportar tool calling**. Um modelo sem esse suporte
> nunca chama a ferramenta de consulta, então nunca toca o dataset e não tem como
> responder. Confira antes com `ollama show <modelo>`: a capacidade `tools`
> precisa estar listada. `gemma3:4b`, por exemplo, **não** a tem.
>
> Validado com `qwen3.5:4b` — ver [Validação com modelo real](#validação-com-modelo-real).

---

## Tecnologias

| Tecnologia | Papel | Por quê |
|---|---|---|
| **Python 3.11+** | Linguagem | — |
| **LangGraph** | Orquestra o ciclo do agente | Estado explícito e controle do loop; grafo próprio em vez do prebuilt ([ADR 0002](docs/adr/0002-langgraph-stategraph-over-prebuilt.md)) |
| **LangChain** | Modelo e ferramentas | Abstração de provider e definição de tools |
| **DuckDB** | Motor analítico | Lê o CSV, infere tipos e agrega sem materializar DataFrame ([ADR 0001](docs/adr/0001-duckdb-over-pandas.md)) |
| **SQLGlot** | Validação do SQL | Análise por AST, não por regex ([ADR 0003](docs/adr/0003-sqlglot-ast-validation.md)) |
| **FastAPI + Uvicorn** | API HTTP | Validação por schema e OpenAPI gerado |
| **Pydantic** | Schemas e configuração | Contrato tipado e `SecretStr` para credenciais |
| **Pytest** | Testes | 100 testes, sem rede |
| **Ruff + Mypy** | Lint e tipagem | — |
| **Docker** | Empacotamento | Execução reproduzível |

Sem Pandas, sem RAG, sem banco vetorial. As justificativas estão nos ADRs.

---

## Arquitetura

```text
                        ┌─────────────────────────────┐
Usuário  ──HTTP──▶      │  FastAPI                    │
(UI / curl)             │  /  /health  /ask           │
                        │  middleware: request_id     │
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
                        │       ▼        └────┬─────┘ │
                        │     [END]           │       │
                        └─────────────────────┼───────┘
                                              ▼
                   ┌──────────────────────────────────────┐
                   │ query_sales_data · inspect_column    │
                   │ submit_answer                        │
                   └──────────────┬───────────────────────┘
                                  ▼
                        ┌──────────────────┐
                        │ SQL Guard        │  AST, somente leitura
                        └────────┬─────────┘
                                 ▼
                        ┌──────────────────┐
                        │ DuckDB + cache   │  view `sales`
                        └────────┬─────────┘
                                 ▼
                            sales.csv
```

O laço `agent → tools → agent` é o self-correction: quando o guard rejeita um SQL
ou a consulta falha, o erro volta ao modelo como `ToolMessage` e ele tenta de novo.
O usuário não recebe o erro — recebe a resposta da segunda tentativa. É isso que
faz do sistema um agente, e não um tradutor de texto para SQL.

---

## Instalação local

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env            # edite conforme abaixo
uvicorn app.main:app --reload
```

### Configuração

Todas as variáveis são opcionais; os padrões estão em `.env.example`.

| Variável | Padrão | Descrição |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` ou `ollama` |
| `LLM_MODEL` | vazio | Vazio usa o padrão do provider (`gpt-4o-mini` / `qwen3.5:4b`) |
| `OPENAI_API_KEY` | — | Exigida quando o provider é `openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | No Docker, use `host.docker.internal` |
| `DATASET_PATH` | `dataset/sales.csv` | |
| `MAX_QUERY_ROWS` | `100` | Teto de linhas por consulta |
| `MAX_AGENT_TURNS` | `6` | Cota de turnos do agente |
| `LLM_TIMEOUT_SECONDS` | `30` | |
| `LOG_LEVEL` | `INFO` | |

---

## Uso

### Interface web

<http://localhost:8000> — campo de pergunta, as cinco perguntas do enunciado como
atalho, e render da resposta com premissas, ressalvas e o trace de execução
mostrando o SQL gerado.

### API

```bash
curl -X POST localhost:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Qual produto foi mais vendido?"}'
```

```bash
curl localhost:8000/health
```

Documentação interativa gerada pelo FastAPI em <http://localhost:8000/docs>.

### Formato da resposta

Trace real, capturado de uma execução contra `qwen3.5:4b` via Ollama:

```json
{
  "answer": "O produto mais vendido foi o **Product_1359**, que teve um total de **95.112.506** unidades vendidas no período analisado (de 2012-01-01 a 2012-12-31).\n\nO segundo produto mais vendido foi o Product_1248, com 53.245.741 unidades, e o terceiro lugar ficou para o Product_1341, com 44.709.999 unidades vendidas.",
  "assumptions": ["A métrica utilizada foi a quantidade total vendida (SUM(actual_quantity)). Se o interesse fosse faturamento, seria SUM(actual_quantity * actual_price), o que resultaria numa ordem diferente."],
  "warnings": [
    "O dataset cobre apenas um ano inteiro de vendas (2012).",
    "Foram analisadas 203.635 linhas do dataset."
  ],
  "metadata": {
    "request_id": "6e9b00ccbcea4c78",
    "turns": 2,
    "total_ms": 79840.89,
    "data_queried": true,
    "trace": [
      {
        "name": "query_sales_data",
        "args": { "sql": "SELECT product_id, SUM(actual_quantity) as total_sold FROM sales GROUP BY product_id ORDER BY total_sold DESC LIMIT 10" },
        "status": "ok",
        "elapsed_ms": 249.31,
        "sql": "SELECT product_id, SUM(actual_quantity) AS total_sold FROM sales GROUP BY product_id ORDER BY total_sold DESC LIMIT 10",
        "row_count": 10,
        "cache_hit": false,
        "error": null
      },
      { "name": "submit_answer", "status": "ok" }
    ]
  }
}
```

O `trace` é o recurso mais útil da resposta: ele mostra o **SQL exato** que o
agente escreveu, então qualquer número pode ser reconferido à mão. O campo `sql`
é o pós-guard, com o `LIMIT` já aplicado.

`data_queried` é o único fato verificável sobre a fundamentação da resposta: ele é
verdadeiro somente quando existe um `query_sales_data` com status `ok` no trace.
Ele **informa em vez de bloquear** — uma recusa legítima ("qual a previsão para
2030?") não precisa consultar nada e responde com `data_queried: false`.

### O que este trace revela sobre modelos pequenos

Nesta execução o modelo enviou `assumptions` como uma **string contendo JSON
malformado** e `warnings` como um **objeto**, em vez das listas que o schema pede.
O JSON acima mostra o resultado já normalizado.

Sem tratamento, um `list()` sobre esses valores produziria uma lista de caracteres
e uma lista de chaves — foi exatamente o que aconteceu na primeira execução real,
com cerca de 200 itens de um caractere na resposta da API. `normalize_text_list`
existe por causa disso, e a normalização precisa acontecer no grafo, não na
ferramenta: o LangChain valida os argumentos contra o schema Pydantic antes de
executar o corpo da tool, mas o nó que encerra o grafo lê os `tool_calls` crus.

---

## Perguntas de exemplo

As cinco do enunciado, disponíveis como atalho na interface:

1. Qual produto foi mais vendido?
2. Qual local teve maior volume de vendas?
3. Qual foi o total de vendas no primeiro trimestre de 2012?
4. Qual a diferença entre quantidade planejada e realizada?
5. Qual o impacto das promoções no preço e volume vendido?

Comportamentos que valem observar:

- **"Qual foi o total de vendas?"** é ambíguo — pode ser quantidade
  (953.555.461 unidades) ou faturamento (R$ 154,35 bilhões). O agente escolhe uma
  leitura e **declara a escolha** em `assumptions`, mencionando a alternativa.
- **A pergunta sobre promoções** é respondida em duas metades: o efeito no preço é
  quantificado (é determinístico e verificável), e o efeito no volume é
  **delimitado** em `warnings`, porque a amostra não sustenta atribuição causal.

---

## Testes

```bash
pytest                    # 124 testes, sem rede e sem chave
ruff check . && ruff format --check .
mypy
```

Com a aplicação de pé e um provider configurado, o golden set roda contra o modelo
real:

```bash
python evals/run_evals.py
python evals/run_evals.py --only top_product     # um caso só
```

Três camadas com naturezas diferentes ([ADR 0006](docs/adr/0006-testing-a-nondeterministic-system.md)):

| Camada | Arquivo | O que garante |
|---|---|---|
| Ground truth | `tests/test_ground_truth.py` | Os números estão certos. SQL direto, sem IA. |
| SQL Guard | `tests/test_sql_guard.py` | Nada além de leitura da tabela `sales` passa. |
| Agente | `tests/test_agent.py` | O grafo se comporta: self-correction, cota de turnos, degradação. |
| API | `tests/test_api.py` | Contrato HTTP, validação e erros sem stack trace. |
| Evals | `evals/` | O agente ainda chega ao resultado certo com um modelo real. |

O agente é testado com um modelo falso (`tests/fakes.py`), então a suíte roda sem
rede, sem chave e sem consumir tokens.

Os evals ficam fora do `pytest` porque medem outra coisa: os testes garantem que o
**código** está correto, o golden set mede se o **agente** continua chegando lá.

A asserção central deles não é sobre a prosa. O runner extrai o SQL que o agente
escreveu do trace e **o re-executa contra o mesmo DuckDB**, conferindo se produz o
valor esperado. Uma asserção secundária compara o texto com os dígitos
normalizados. Isso separa duas falhas distintas: *chegou ao dado certo* e *narrou o
dado certo* — um modelo pode acertar a primeira e inventar um número na segunda.

---

## O que os dados revelam

Achados verificados com SQL antes de qualquer código ser escrito. Vários deles
mudaram o desenho da solução:

- **`promotion_type` não tem NULL.** A ausência de promoção é a string literal
  `'None'`. Um `WHERE promotion_type IS NOT NULL` devolve as 203.635 linhas sem
  erro nenhum. É a razão de a ferramenta `inspect_column` existir.
- **Promoções são 12 linhas, em 2 produtos.** `Product_0001` e `Product_0002`.
  Desconto de **exatamente -20%** nos dois casos. O efeito no preço é mensurável;
  o efeito no volume não é atribuível com essa amostra.
- **`actual_price` só difere de `planned_price` nessas 12 linhas.** Fora de
  promoção, o preço praticado é sempre o planejado.
- **`service_level` é constante `0.98`** nas 203.635 linhas. Coluna sem variação —
  o profiling detecta isso sozinho e o prompt avisa o agente.
- **Existem 1.297 grupos de linhas exatamente duplicadas** e não há chave única.
  Podem ser transações legítimas no mesmo dia ou erro de ingestão; o dataset não
  permite distinguir.
- **`Whse_J` concentra 74% dos registros** (150.013 de 203.635), o que explica boa
  parte da liderança dele em volume.
- **A data é `DD/MM/YYYY`.** Se fosse interpretada como `MM/DD`, todo filtro por
  período mentiria em silêncio. Há teste travando isso.

---

## Segurança

| Risco | Mitigação |
|---|---|
| SQL destrutivo gerado pelo modelo | Validação de AST; só `SELECT`/`UNION` sobre `sales` |
| Leitura de arquivo do container via SQL | Funções de tabela (`read_csv_auto`, `glob`, …) bloqueadas; toda tabela sem nome é rejeitada |
| Execução de código arbitrário | Nenhum `exec`/`eval`; agentes de CSV/Pandas do LangChain proibidos ([ADR 0005](docs/adr/0005-no-pandas-csv-agent.md)) |
| Vazamento de credencial | `SecretStr`; teste asserindo que a chave não aparece em `repr` nem em `model_dump` |
| Vazamento de detalhe interno em erro | Corpo de 5xx é genérico; o detalhe vai só para o log |
| Consumo descontrolado de tokens | Cota de turnos mais `recursion_limit` |
| Resposta grande demais | `LIMIT` injetado e reduzido quando o modelo pede alto demais |
| Container comprometido | Usuário não-root, imagem slim, sem escrita em disco |

---

## Decisões arquiteturais

Cada uma documentada com contexto, consequências e alternativas rejeitadas:

1. [DuckDB em vez de Pandas](docs/adr/0001-duckdb-over-pandas.md)
2. [LangGraph com `StateGraph` explícito, não `create_react_agent`](docs/adr/0002-langgraph-stategraph-over-prebuilt.md)
3. [Validação de SQL por AST, com SQLGlot](docs/adr/0003-sqlglot-ast-validation.md)
4. [Três ferramentas, e o critério de tool vs prompt](docs/adr/0004-tools-vs-prompt.md)
5. [Não usar `create_csv_agent` / `create_pandas_dataframe_agent`](docs/adr/0005-no-pandas-csv-agent.md)
6. [Como testar um sistema não determinístico](docs/adr/0006-testing-a-nondeterministic-system.md)

O ADR 0005 é o mais importante: o caminho óbvio dentro do LangChain para "agente
que analisa CSV" executa Python gerado pelo LLM. Este projeto existe, em boa
medida, para não tomar esse atalho.

---

## Validação com modelo real

Executado ponta a ponta contra **`qwen3.5:4b`** (4.7B, Q4_K_M) servido por Ollama
0.32.6 num servidor remoto, alcançado por túnel SSH — sem expor a porta 11434 na
rede.

Resultado de `python evals/run_evals.py` — **8/8 aprovados**:

```text
CASO                      RESULTADO   TEMPO     TURNOS
------------------------------------------------------------------------
top_product               APROVADO      86.6s      2
top_location              APROVADO     102.7s      3
period_total              APROVADO      84.0s      2
plan_gap                  APROVADO      82.6s      2
promo_impact              APROVADO     292.1s      6
ambiguous_sales           APROVADO     155.2s      4
promotion_null_trap       APROVADO     115.3s      3
out_of_scope              APROVADO      57.4s      1
------------------------------------------------------------------------
TAXA DE ACERTO: 8/8   tempo medio 122.0s por pergunta
```

Os cinco primeiros são as perguntas de exemplo do enunciado. Em cada um deles o
SQL escrito pelo agente foi **reexecutado pelo harness** e produziu o valor de
ground truth — `Product_1359` / 95.112.506, `Whse_J` / 617.421.620, e assim por
diante.

Três casos merecem destaque, porque mostram comportamento e não só aritmética:

- **`promotion_null_trap`** — perguntado quantas vendas tiveram promoção, o agente
  escreveu `WHERE promotion_type = 'Flash'` e chegou a 12. Evitou sozinho o
  `IS NOT NULL` que devolveria as 203.635 linhas.
- **`period_total`** — filtrou com `date >= '2012-01-01' AND date <= '2012-03-31'`,
  confirmando o parsing `DD/MM/YYYY` de ponta a ponta.
- **`ambiguous_sales`** — consultou quantidade **e** faturamento, e declarou em
  `assumptions` qual leitura usou.

Na pergunta de promoções o agente gastou 6 turnos e 4 consultas antes de concluir,
e registrou a limitação amostral em vez de atribuir causalidade.

**Latência: 57 a 292 s por pergunta**, média 122 s. É quase toda inferência do
modelo de 4B — as consultas ao DuckDB levaram entre 1,8 e 332 ms.

**Docker validado**: `docker build` bem-sucedido, container sobe como usuário
não-root, `HEALTHCHECK` reporta `healthy`, e `/ask` respondeu o ground truth de
dentro do container alcançando o túnel via `host.docker.internal`.

### O que o modelo de 4B não faz bem

- **Não respeita o schema de tipos** nos argumentos de ferramenta: manda string ou
  objeto onde o contrato pede lista. Tratado por `normalize_text_list`.
- **Ignora a ferramenta de saída em ~30% das execuções**, respondendo em prosa. A
  resposta é preservada e um `warning` explícito é acrescentado.
- **Raramente devolve resposta vazia** (1 em ~16 execuções): sem tool call e sem
  texto. Nesse caso a requisição falha de forma controlada em vez de devolver
  HTTP 200 com `answer` em branco.

Nenhuma dessas limitações afetou a correção dos números, porque quem calcula é o
DuckDB. Um modelo maior reduziria os dois primeiros itens; a arquitetura não muda.

---

## Limitações conhecidas

**Latência alta com modelo local.** ~90 s por pergunta com o `qwen3.5:4b`, quase
tudo em inferência — o DuckDB responde em milissegundos. Um modelo maior ou uma
API hospedada reduziria isso a poucos segundos, sem tocar na arquitetura.

**Sem memória entre perguntas.** Cada requisição é independente; não há follow-up
("e no ano anterior?"). O LangGraph resolve isso com `MemorySaver` e `thread_id`,
mas em produção seria Redis, não memória de processo.

**Duplicatas não tratadas.** Os 1.297 grupos idênticos são contados normalmente
nas agregações. Decidir se são transações legítimas ou erro de ingestão exige
conhecimento do negócio que o dataset não carrega.

---

## Próximos passos

1. Automatizar o golden set como harness reproduzível (`evals/`), hoje executado
   manualmente — ver [ADR 0006](docs/adr/0006-testing-a-nondeterministic-system.md)
2. Comparar `qwen3.5:4b` com um modelo maior medindo a regressão, em vez de opinar
3. CI no GitHub Actions com `ruff`, `mypy` e `pytest`
4. Conversas multi-turno com `MemorySaver`
5. Streaming via `astream_events`, mostrando o agente raciocinando

---

## Estrutura

```text
app/
├── main.py              app factory, lifespan, exception handlers
├── config.py            Settings (provider, modelo, limites)
├── schemas.py           contrato HTTP
├── errors.py            exceções de domínio
├── logging_setup.py     logging JSON com request_id
├── api/                 rotas e middleware
├── agent/               grafo, estado, prompts, ferramentas, modelo
└── analytics/           repositório DuckDB, profiling, SQL guard
dataset/sales.csv        dataset do desafio
docs/adr/                decisões arquiteturais
static/index.html        interface web
tests/                   100 testes
```
