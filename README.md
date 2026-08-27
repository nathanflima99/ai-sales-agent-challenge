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
ollama pull llama3.1
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=ollama \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  ai-sales-agent
```

> O modelo Ollama **precisa suportar tool calling** — `llama3.1`, `qwen2.5` ou
> `mistral-nemo`. Um modelo sem esse suporte nunca chama a ferramenta de consulta,
> então nunca toca o dataset e não tem como responder.

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
| `LLM_MODEL` | vazio | Vazio usa o padrão do provider (`gpt-4o-mini` / `llama3.1`) |
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

```json
{
  "answer": "O produto mais vendido foi o Product_1359, com 95.112.506 unidades.",
  "assumptions": [
    "'mais vendido' interpretado como soma de actual_quantity, não faturamento"
  ],
  "warnings": [],
  "metadata": {
    "request_id": "7cf411e07dde453e",
    "turns": 2,
    "total_ms": 3184.7,
    "trace": [
      {
        "name": "query_sales_data",
        "args": { "sql": "SELECT product_id, SUM(actual_quantity) AS total FROM sales GROUP BY product_id ORDER BY total DESC LIMIT 1" },
        "status": "ok",
        "elapsed_ms": 41.2,
        "sql": "SELECT product_id, SUM(actual_quantity) AS total FROM sales GROUP BY product_id ORDER BY total DESC LIMIT 100",
        "row_count": 1,
        "cache_hit": false
      },
      { "name": "submit_answer", "status": "ok" }
    ]
  }
}
```

O `trace` é o recurso mais útil da resposta: ele mostra o **SQL exato** que o
agente escreveu, então qualquer número pode ser reconferido à mão. Note que o
`sql` registrado é o pós-guard — com o `LIMIT` já injetado.

> ⚠️ O JSON acima ilustra o **formato**. Um trace capturado de uma execução real
> ainda não foi incluído — ver [Limitações conhecidas](#limitações-conhecidas).

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
pytest                    # 100 testes, sem rede e sem chave
ruff check . && ruff format --check .
mypy
```

Três camadas com naturezas diferentes ([ADR 0006](docs/adr/0006-testing-a-nondeterministic-system.md)):

| Camada | Arquivo | O que garante |
|---|---|---|
| Ground truth | `tests/test_ground_truth.py` | Os números estão certos. SQL direto, sem IA. |
| SQL Guard | `tests/test_sql_guard.py` | Nada além de leitura da tabela `sales` passa. |
| Agente | `tests/test_agent.py` | O grafo se comporta: self-correction, cota de turnos, degradação. |
| API | `tests/test_api.py` | Contrato HTTP, validação e erros sem stack trace. |

O agente é testado com um modelo falso (`tests/fakes.py`), então a suíte roda sem
rede, sem chave e sem consumir tokens.

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

## Limitações conhecidas

**O caminho feliz completo não foi executado contra um provider real.** Não havia
credencial de LLM disponível no ambiente de desenvolvimento. Todo o agente foi
validado com um modelo falso que exercita o grafo, e toda a camada analítica com
SQL determinístico — mas nenhuma chamada real a OpenAI ou Ollama aconteceu.
Consequências: o trace de exemplo acima ilustra o formato em vez de ser capturado,
e os evals ainda não têm resultado.

**A imagem Docker não foi construída.** Docker não estava instalado na máquina de
desenvolvimento. O `Dockerfile` foi escrito com cuidado e a etapa de maior risco
— a construção do wheel com pacote stub, que permite cachear as dependências —
foi validada localmente com `pip`, mas o build completo não rodou.

**Evals ainda não implementados.** O desenho está no
[ADR 0006](docs/adr/0006-testing-a-nondeterministic-system.md): golden set com as
cinco perguntas do enunciado, asserção primária sobre o resultado da ferramenta no
trace e secundária sobre o texto com dígitos normalizados.

**Sem memória entre perguntas.** Cada requisição é independente; não há follow-up
("e no ano anterior?"). O LangGraph resolve isso com `MemorySaver` e `thread_id`,
mas em produção seria Redis, não memória de processo.

**Duplicatas não tratadas.** Os 1.297 grupos idênticos são contados normalmente
nas agregações. Decidir se são transações legítimas ou erro de ingestão exige
conhecimento do negócio que o dataset não carrega.

---

## Próximos passos

1. Rodar o golden set contra um provider real e publicar a taxa de acerto aqui
2. Construir e publicar a imagem Docker
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
