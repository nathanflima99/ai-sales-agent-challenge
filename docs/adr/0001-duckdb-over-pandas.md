# ADR 0001 — DuckDB em vez de Pandas

## Contexto

A aplicação precisa ler `sales.csv` (203.635 linhas, 11 MB), inferir tipos,
agregar, filtrar e ordenar em resposta a perguntas em linguagem natural. O
caminho reflexo em Python seria Pandas.

## Decisão

Usar DuckDB, registrando o CSV como uma view somente leitura chamada `sales`.
Nenhum DataFrame existe na aplicação.

## Consequências

**Positivas**

- O LLM já sabe escrever SQL. Gerar SQL é uma tarefa que ele faz bem e que
  podemos validar antes de executar; gerar código Pandas seria gerar código
  arbitrário, com uma superfície de ataque incomparavelmente maior (ver
  [ADR 0005](0005-no-pandas-csv-agent.md)).
- Uma única camada calcula. Ter Pandas e SQL fazendo a mesma agregação é risco
  de divergência entre dois números que deveriam ser o mesmo, não robustez.
- `read_csv_auto` resolve leitura, inferência de tipos e delimitador. O profiling
  do dataset sai em SQL puro, sem código de análise adicional.
- View em vez de `CREATE TABLE`: o arquivo é lido sob demanda, sem materializar
  uma segunda cópia dos dados em memória.

**Negativas**

- A conexão DuckDB não suporta uso simultâneo entre threads, e o FastAPI despacha
  handlers síncronos num threadpool. Resolvido com um `cursor()` por consulta.
- Manipulações que em Pandas seriam triviais (pivot complexo, aplicação de função
  Python linha a linha) ficam mais trabalhosas. Nenhuma delas apareceu no escopo.

## Alternativas rejeitadas

**Pandas + `df.query()`** — mantém o problema de precisar traduzir linguagem
natural em operação, sem ganhar a validação sintática que o SQL permite.

**SQLite** — funcionaria, mas exigiria criar tabela e carregar os dados
explicitamente, e é mais lento em agregação analítica. O DuckDB é colunar e foi
desenhado exatamente para este caso.

## Como escalaria

O mesmo SQL roda sobre Parquet no S3 trocando a definição da view por
`read_parquet('s3://...')`. Para volumes que não cabem num processo, a troca é do
motor — Postgres, BigQuery, Athena — e o guard de SQL e o agente continuam iguais,
porque a fronteira já é "SQL validado", não "arquivo local".
