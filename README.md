# AI Sales Agent

[![CI](https://github.com/nathanflima99/ai-sales-agent-challenge/actions/workflows/ci.yml/badge.svg)](https://github.com/nathanflima99/ai-sales-agent-challenge/actions/workflows/ci.yml)

Agente de IA que responde perguntas em linguagem natural sobre `dataset/sales.csv`
(203.635 registros de vendas de 2012).

O princípio que organiza todo o projeto: **o modelo interpreta e narra; o DuckDB
calcula.** Nenhum número que aparece numa resposta sai da inferência do LLM — todos
vêm de uma consulta SQL que é validada antes de executar e fica visível no trace da
resposta.

O enunciado original do desafio está em [`ENUNCIADO.pdf`](ENUNCIADO.pdf).

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

### Com Ollama local (sem chave e sem custo por token)

```bash
ollama pull qwen3.5:4b
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=ollama \
  -e LLM_MODEL=qwen3.5:4b \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  ai-sales-agent
```

### Com Ollama Cloud (sem instalar Ollama localmente)

A API hospedada do Ollama pode ser usada diretamente. Crie uma API key na sua conta
Ollama e configure o endpoint remoto e a chave por variável de ambiente:

```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen3.5:397b
OLLAMA_BASE_URL=https://ollama.com
OLLAMA_API_KEY=sua-chave-aqui
```

Depois suba a aplicação normalmente:

```bash
uvicorn app.main:app --reload
```

Ou via Docker:

```bash
docker run --rm -p 8000:8000 \
  -e LLM_PROVIDER=ollama \
  -e LLM_MODEL=qwen3.5:397b \
  -e OLLAMA_BASE_URL=https://ollama.com \
  -e OLLAMA_API_KEY="$OLLAMA_API_KEY" \
  ai-sales-agent
```

`OLLAMA_API_KEY` é opcional para servidores locais sem autenticação e obrigatória
quando `OLLAMA_BASE_URL=https://ollama.com`. A chave é armazenada como `SecretStr`
e não é escrita nos logs pelo projeto. No acesso direto a `https://ollama.com`, use
em `LLM_MODEL` um nome retornado por `/api/tags`; `qwen3.5:397b` é o exemplo atual.
O script `TESTAR_OLLAMA_CLOUD.bat` consulta esse catálogo e seleciona automaticamente
um Qwen 3.5 disponível para a conta.

> O modelo Ollama **precisa suportar tool calling**. Um modelo sem esse suporte
> nunca chama a ferramenta de consulta, então nunca toca o dataset e não tem como
> responder. Confira antes com `ollama show <modelo>`: a capacidade `tools`
> precisa estar listada. `gemma3:4b`, por exemplo, **não** a tem.
>
> Mas a lista é condição necessária, não suficiente. O `qwen2.5-coder:7b` declara
> `tools` e mesmo assim não chamou ferramenta nenhuma em nove execuções — ver
> [por que um modelo de 4B](#por-que-um-modelo-de-4b-e-não-o-maior-disponível).
> Confirme com uma pergunta real e olhe `metadata.data_queried`.
>
> `qwen3.5:4b` foi validado ponta a ponta — ver
> [Validação com modelo real](#validação-com-modelo-real).

### Thinking / reasoning

O Sales usa `OLLAMA_THINKING=true` por padrão. Em `langchain-ollama==1.1.0`, o
valor é enviado ao Ollama como `ChatOllama(reasoning=...)`, equivalente a `think`
na API do Ollama.

O padrão foi decidido por medição, não por intuição — e a intuição estava errada.

O raciocínio inicial era desligar: o cálculo é do DuckDB, então o modelo só
precisaria narrar, e desligar economizaria latência. O golden set foi executado
nos dois modos, mesma máquina, mesmo modelo, mesmo prompt:

| | `true` | `false` |
|---|---|---|
| Taxa de acerto | **8/8** | **3/8** |
| Tempo médio | 122 s | **53 s** |

A latência de fato cai 57%. Mas a taxa de acerto desaba, e o padrão das falhas
contradiz a premissa: **o SQL continuou correto em todos os casos**. O que degrada
é justamente interpretar e narrar.

O caso mais ilustrativo foi a diferença entre planejado e realizado. Sem thinking,
o modelo pediu ao DuckDB os dois totais, recebeu 949.259.991 e 953.555.461
corretamente — e então fez a subtração de cabeça, respondendo **−4.305.470** em
vez de 4.295.470. Errou o valor e o sinal, enquanto o próprio texto afirmava
corretamente que se vendeu mais do que o planejado.

Outras falhas do modo desligado: consultar os dados e não citar o número obtido,
não preencher `assumptions` numa pergunta ambígua, e uma vez responder sobre
promoções **sem consultar o dataset** (`data_queried: false`).

Para desligar conscientemente, quando latência valer mais que corretude:

```env
OLLAMA_THINKING=false
```

Ao repetir o experimento, não altere prompts nem golden set — assim a única
variável continua sendo thinking ligado/desligado. E rode mais de uma vez por
modo: os números acima são de uma execução de cada lado, o que basta para uma
diferença desse tamanho, mas não para distinções sutis.

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
| **Pytest** | Testes | Suíte determinística sem rede |
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

Os padrões estão em `.env.example`.

| Variável | Padrão | Descrição |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` ou `ollama` |
| `LLM_MODEL` | vazio | Vazio usa o padrão do provider (`gpt-4o-mini` / `qwen3.5:4b`) |
| `OPENAI_API_KEY` | — | Exigida quando o provider é `openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Host local, remoto ou `https://ollama.com` |
| `OLLAMA_API_KEY` | — | Opcional localmente; obrigatória para acesso direto a `ollama.com` |
| `OLLAMA_THINKING` | `true` | Reasoning do Ollama. Desligar troca corretude por latência — ver [Thinking / reasoning](#thinking--reasoning) |
| `DATASET_PATH` | `dataset/sales.csv` | |
| `MAX_QUERY_ROWS` | `100` | Teto de linhas por consulta |
| `MAX_AGENT_TURNS` | `15` | Cota de turnos. Retry de ferramenta, de resposta vazia e de verificação consomem do mesmo orçamento |
| `LLM_TIMEOUT_SECONDS` | `30` | |
| `LOG_LEVEL` | `INFO` | |

---

## Uso

### Interface web

<http://localhost:8000> — campo de pergunta, as cinco perguntas do enunciado como
atalho, e render da resposta com premissas, ressalvas e o trace de execução
mostrando o SQL gerado.

Durante a espera ela mostra tempo decorrido e a duração típica do provider em
uso. Com modelo local são 1 a 4 minutos, e um texto parado por tanto tempo não
distingue "processando" de "travado" — foi exatamente a dúvida que apareceu
testando a aplicação à mão. O contador não estima progresso, porque o front não
tem como saber em que passo o agente está: a resposta chega inteira, de uma vez.
Ele responde só a pergunta que o usuário realmente tem parado na tela.

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
    "numbers_verified": true,
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

Dois campos do `metadata` dizem o que conseguimos **provar** sobre a resposta, e
os nomes foram escolhidos por isso — nenhum deles afirma que ela está correta.

`data_queried` é verdadeiro somente quando existe um `query_sales_data` com
status `ok` no trace.

`numbers_verified` é falso quando a resposta cita algum número que nenhuma
consulta devolveu — o modelo calculou de cabeça — e a cota de turnos acabou antes
da correção. Nesse caso a resposta é entregue com um aviso, e o campo permite ao
cliente recusá-la sem interpretar prosa. Ver
[a trava de números](#a-trava-de-números).
Ele **informa em vez de bloquear** — uma recusa legítima ("qual a previsão para
2030?") não precisa consultar nada e responde com `data_queried: false`.

### A trava de números

O princípio do topo deste README — *nenhum número sai da inferência do LLM* — era,
até certo ponto, uma regra escrita no prompt. E instrução é seguida de forma
probabilística.

O caso que provou isso: perguntado pela **diferença** entre planejado e realizado,
o modelo escreveu

```sql
SELECT SUM(planned_quantity), SUM(actual_quantity) FROM sales
```

recebeu 949.259.991 e 953.555.461 corretos, e **subtraiu na resposta**, devolvendo
−4.305.470 onde o correto era 4.295.470. Errou o valor e o sinal. A conta era o
enunciado da pergunta.

Hoje isso é verificado, não pedido. O nó de ferramentas guarda os números que cada
consulta devolveu; o nó de encerramento confere que todo número mostrado ao
usuário — em `answer`, `assumptions` e `warnings` — está entre eles. O que não
estiver volta ao modelo pelo mesmo mecanismo que trata SQL rejeitado.

A verificação é conservadora, porque uma trava que gera falso positivo é desligada
e aí deixa de existir. Ela ignora números de um dígito, anos e componentes de
data, valores que já estavam na pergunta ou no contexto dado ao modelo, e
arredondamentos de um valor consultado — tolerando 1 no último dígito, que é o
carry máximo de um arredondamento. `4.305.470` contra `4.295.470` difere em 10.000
e continua reprovado.

Numa medição de 24 execuções ela disparou 7 vezes, **todas verdadeiras**. Depois
de o prompt passar a contrastar valores derivados com exemplos de SQL, outras 24
execuções não a dispararam nenhuma vez. Os dois números estão na tabela de
validação mais abaixo, com o que mudou entre eles.

**O que ela não faz:** garantir que a resposta esteja certa. Um SQL válido pode
responder a pergunta errada, e nenhuma verificação sintática pega isso. Ela
garante rastreabilidade, não correção.

Um caso concreto, capturado testando a aplicação à mão. Perguntado pelo produto
mais vendido, o modelo escreveu no meio da investigação:

```sql
SELECT SUM(actual_quantity) AS total_vendas
FROM sales, (SELECT product_id, SUM(actual_quantity) AS prod_total
             FROM sales GROUP BY product_id) AS t
WHERE t.product_id = 'Product_1359'
```

Falta o `JOIN ... ON`: é um produto cartesiano que cruza as 203.635 linhas com a
única linha filtrada e devolve `953.555.461` — o total do dataset inteiro, não o
do produto. **Nenhuma das duas travas teria impedido** a resposta de citar esse
número: o SQL é válido, somente-leitura e na tabela permitida, então o guard
aprova; e o valor veio mesmo de uma consulta, então a verificação de números
aprova. Quem descartou foi o próprio modelo, que rodou a consulta certa em
seguida. Deu certo por comportamento, não por garantia.

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
pytest
ruff check . && ruff format --check .
mypy
```

Estes três comandos rodam em cada pull request e a cada push na `main`
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), em Python 3.11 e 3.12 —
as duas pontas do `requires-python`, para que a compatibilidade declarada seja
verificada e não apenas afirmada. O workflow também falha se `dataset/sales.csv`
estiver ausente: os testes de ground truth pulam sozinhos sem o arquivo, e uma
suíte verde sem eles não provaria nada.

O golden set **não** entra na CI. Ele depende de um modelo real e o resultado
varia entre execuções; virar check obrigatório o transformaria numa fonte de
vermelho aleatório. É medição, não teste — a distinção está no
[ADR 0006](docs/adr/0006-testing-a-nondeterministic-system.md).

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
| Provider | `tests/test_model.py` | Thinking, autenticação Ollama Cloud e isolamento do OpenAI. |
| Evals | `evals/` | O agente ainda chega ao resultado certo com um modelo real. |

O agente é testado com um modelo falso (`tests/fakes.py`), então a suíte roda sem
rede, sem chave e sem consumir tokens. Os testes do provider apenas instanciam os
clientes; não fazem requisições externas.

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
| Vazamento de credencial | `SecretStr`; API keys não são registradas em logs |
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

### O número, com a variância junto

Três execuções de `python evals/run_evals.py`, na configuração atual:

```text
rodada 1:  8/8   118.2s por pergunta
rodada 2:  8/8   106.2s
rodada 3:  8/8   108.2s
```

**24/24, tempo médio 111 s.** Casos entre 55 s e 252 s.

Reportar a faixa em vez de um ponto continua sendo o certo, mesmo com três
rodadas limpas. Uma execução isolada deste golden set já deu 5/8 com código que
hoje dá 8/8; quem clonar o repositório e rodar uma vez precisa saber disso antes
de concluir que algo quebrou. O que mudou entre aquelas medições e esta está
registrado logo abaixo — não foi o modelo que melhorou.

Os cinco primeiros casos são as perguntas de exemplo do enunciado. Em cada um o
SQL escrito pelo agente foi **reexecutado pelo harness** e produziu o valor de
ground truth — `Product_1359` / 95.112.506, `Whse_J` / 617.421.620, e assim por
diante.

### Por que um modelo de 4B, e não o maior disponível

O servidor de teste tem uma **AMD RX 580 de 8 GB**. Isso define o teto: um modelo
de 14B ocuparia ~9 GB e transbordaria para a CPU, e a latência — já em minutos —
ficaria proibitiva. Só um modelo instalado era maior que o `qwen3.5:4b`, e ele
foi medido no mesmo golden set:

| | `qwen3.5:4b` | `qwen2.5-coder:7b` |
|---|---|---|
| Parâmetros | 4,7B | 7,6B |
| Taxa de acerto | **8/8** | **1/8** |
| Consultas ao dataset | sempre | **nunca** |
| Tempo médio | ~130 s | 27 s |

O modelo maior nunca chamou uma ferramenta. Nove execuções, zero consultas ao
DuckDB, `data_queried: false` em todas — respondeu em prosa direto, com texto
fluente e números plausíveis. É rápido porque não faz nada.

Duas lições ficam daqui.

**Declarar `tools` não é saber usar.** O `ollama show` lista a capacidade porque o
template do modelo a suporta; se o modelo *decide* usá-la é outra coisa. É uma
falha pior que a do `gemma3:4b`, que ao menos não declara — esta é silenciosa.

**E é onde o `data_queried` se paga.** Sem ele, aquelas nove respostas passariam
por legítimas: bem escritas, bem formatadas, com números da ordem de grandeza
certa. Nove `data_queried: false` seguidos são um diagnóstico instantâneo.

Para um modelo realmente maior, o caminho neste projeto não é hardware local e
sim [Ollama Cloud](#com-ollama-cloud-sem-instalar-ollama-localmente), que remove
o teto de VRAM.

### O que a trava de números mudou

A verificação de que todo valor citado veio de uma consulta foi medida contra a
ausência dela, nas mesmas condições:

| | Sem trava | Trava, 1ª versão | Trava calibrada |
|---|---|---|---|
| Rodadas | 6/8, 8/8, 5/8 | 8/8, 8/8, 7/8 | **8/8, 8/8, 8/8** |
| Pior caso | 5 | 7 | **8** |
| Tempo médio | ~83 s | ~130 s | ~111 s |
| Disparos | — | 7 em 24 | **0 em 24** |

Ela custa cerca de 28 s por pergunta e leva o pior caso de 5 para 8 — que é o que
importa, porque o pior caso é o que alguém encontra ao rodar uma vez.

Os sete disparos da versão intermediária foram todos atribuídos à pergunta e
todos procediam. O mais ilustrativo: perguntado pela diferença entre planejado e
realizado, o modelo narrou `4.295.470` sem que nenhuma consulta o tivesse
devolvido — e, numa das execuções, o mesmo valor arredondado como "4,3 milhões".
Nos dois casos ele tinha calculado de cabeça.

**Zero disparos na versão final não significa que a trava ficou permissiva.** Ela
foi afrouxada num ponto só, e estreito: passou a aceitar truncamento além de
arredondamento, porque reprovava "953 milhões" narrando `953.531.302`. Esse
afrouxamento não alcança o caso do `4.295.470`, que continua reprovado nos testes.

O que explica a queda é o prompt, que passou a contrastar valores derivados com
exemplos de SQL certo e errado, e a cota de turnos, que subiu para 15. O modelo
parou de calcular de cabeça porque foi instruído melhor e teve espaço para
consultar de novo — não porque a verificação parou de olhar. A distinção importa:
uma trava silenciosa por estar cega é pior que trava nenhuma, já que passa
confiança sem entregar nada.

Três casos merecem destaque, porque mostram comportamento e não só aritmética:

- **`promotion_null_trap`** — perguntado quantas vendas tiveram promoção, o agente
  escreveu `WHERE promotion_type = 'Flash'` e chegou a 12. Evitou sozinho o
  `IS NOT NULL` que devolveria as 203.635 linhas.
- **`period_total`** — filtrou com `date >= '2012-01-01' AND date <= '2012-03-31'`,
  confirmando o parsing `DD/MM/YYYY` de ponta a ponta.
- **`ambiguous_sales`** — consultou quantidade **e** faturamento, e declarou em
  `assumptions` qual leitura usou.

Na pergunta de promoções o agente gastou 3 a 4 turnos, quantificou o efeito no
preço (`-33,53` de diferença média sob promoção) e recusou explicitamente
conclusão causal sobre volume, apontando os 12 registros de amostra. É o caso
mais caro do conjunto — 157 s a 252 s — e o que mais depende da cota de turnos:
com o limite original de 6 ele consumia 10 e terminava sem responder.

**Latência: ~111 s por pergunta**, com casos entre 55 s e 252 s. É quase toda
inferência do modelo de 4B — as consultas ao DuckDB levaram entre 1,8 e 332 ms.

**Docker validado**: `docker build` bem-sucedido, container sobe como usuário
não-root, `HEALTHCHECK` reporta `healthy`, e `/ask` respondeu o ground truth de
dentro do container alcançando o túnel via `host.docker.internal`.

### O que o modelo de 4B não faz bem

- **Não respeita o schema de tipos** nos argumentos de ferramenta: manda string ou
  objeto onde o contrato pede lista. Tratado por `normalize_text_list`.
- **Ignora a ferramenta de saída em ~30% das execuções**, respondendo em prosa. A
  resposta é preservada e um `warning` explícito é acrescentado.
- **Às vezes devolve resposta vazia** — sem tool call, sem texto e sem raciocínio.
  Medido em 6 de 32 execuções. O agente pede outra tentativa; quando nem assim
  vem resposta, a requisição falha de forma controlada em vez de devolver HTTP
  200 com `answer` em branco. Não ocorreu nas 24 execuções finais, mas 24 não são
  suficientes para dizer que sumiu.

  **E nem sempre é transitório.** Perguntado pelo produto menos vendido, o modelo
  consultou o dataset e depois devolveu vazio **catorze vezes seguidas**, até
  estourar a cota. Eu tinha suposto que a cota de turnos bastava de limite; ela
  bastava para terminar, não para terminar rápido — foram 5min36s até o erro.
  Hoje o agente desiste após 3 vazias consecutivas (`MAX_CONSECUTIVE_EMPTY`) e
  responde 503, porque a essa altura o diagnóstico é modelo indisponível, não
  agente perdido. O contador zera a cada resposta com conteúdo: o que denuncia
  travamento é a sequência, não o total.
- **Calcula de cabeça quando deveria consultar.** Perguntado pela diferença entre
  planejado e realizado, pediu as duas somas ao banco e subtraiu na resposta.
  É o que a trava de números detecta.

Nenhuma dessas limitações produz número errado sem aviso, porque quem calcula é o
DuckDB e o que ele não calculou é sinalizado. Um modelo maior reduziria as três;
a arquitetura não muda.

---

## Limitações conhecidas

**Latência alta no baseline local.** Média de 111 s por pergunta com `qwen3.5:4b`,
quase tudo em inferência — as consultas ao DuckDB são milissegundos. O modo
thinking fica **ligado** por padrão, e é responsável por boa parte desse custo:
desligá-lo cai para 53 s e derruba o acerto de 8/8 para 3/8, então a troca não
compensa. Um modelo servido em GPU adequada resolveria a latência sem tocar na
arquitetura; a máquina de teste roda em CPU, por falta de CUDA.

**Sem memória entre perguntas.** Cada requisição é independente; não há follow-up
("e no ano anterior?"). O LangGraph resolve isso com `MemorySaver` e `thread_id`,
mas em produção seria Redis, não memória de processo.

**Empates não são declarados.** Perguntado pelo produto *menos* vendido, o agente
escreve `ORDER BY total ASC LIMIT 1` — sintaticamente correto e analiticamente
incompleto, porque **seis produtos empatam em 1 unidade** (`Product_0362`,
`0612`, `0811`, `0812`, `1697`, `1698`). Sem critério de desempate, qual deles
volta não é garantido nem entre execuções. A pergunta simétrica não tem esse
problema — `Product_1359` lidera isolado por quase o dobro —, o que faz o caso
passar despercebido em quem só testa o "mais vendido". O prompt trata ambiguidade
de *definição* (vendas em quantidade ou faturamento); ambiguidade de *resultado*
ele ainda não trata.

**Duplicatas não tratadas.** Os 1.297 grupos idênticos são contados normalmente
nas agregações. Decidir se são transações legítimas ou erro de ingestão exige
conhecimento do negócio que o dataset não carrega.

---

## Próximos passos

1. Repetir o golden set num modelo maior **servido em GPU** — o teste local com
   `qwen2.5-coder:7b` já foi feito e saiu pior (1/8), mas em CPU e sem tool
   calling confiável, o que não isola o efeito do tamanho.
2. Validar o mesmo fluxo com Ollama Cloud usando apenas `OLLAMA_BASE_URL` e
   `OLLAMA_API_KEY`, sem runtime Ollama local.
3. Comparar `qwen3.5:4b` com um modelo maior medindo regressão, em vez de opinar.
4. CI no GitHub Actions com `ruff`, `mypy` e `pytest`.
5. Conversas multi-turno com `MemorySaver`.
6. Streaming via `astream_events`.

---

## Estrutura

```text
app/
├── main.py              app factory, lifespan, exception handlers
├── config.py            Settings (provider, modelo, credenciais, limites)
├── schemas.py           contrato HTTP
├── errors.py            exceções de domínio
├── logging_setup.py     logging JSON com request_id
├── api/                 rotas e middleware
├── agent/               grafo, estado, prompts, ferramentas, modelo
└── analytics/           repositório DuckDB, profiling, SQL guard
dataset/sales.csv        dataset do desafio
docs/adr/                decisões arquiteturais
static/index.html        interface web
tests/                   testes determinísticos e de provider
```
