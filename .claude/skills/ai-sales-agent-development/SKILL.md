---
name: ai-sales-agent-development
description: Primary development playbook for this repository. Use for architecture, implementation, debugging, refactoring, or planning work on the AI sales CSV challenge.
---

# AI Sales Agent Development

## Goal
Build the smallest technically strong solution that answers natural-language questions about `sales.csv` and remains easy to explain in an AI Software Engineer interview.

## Target flow
`User -> FastAPI -> tool-calling loop -> read-only SQL validation -> DuckDB -> sales.csv -> grounded answer`.

## Responsibility split
- LLM: understand intent, choose a tool/query, explain the result.
- DuckDB: filter, aggregate, sort, and calculate.
- Application code: validate inputs, enforce boundaries, execute tools, handle errors, and expose the API.

## Work in this order
1. Bootstrap a runnable API and configuration.
2. Inspect and validate the dataset with deterministic code.
3. Add DuckDB and prove known analytical queries without any LLM.
4. Add the smallest safe SQL boundary.
5. Add one useful analytical tool and a simple model tool-calling loop.
6. Add `/ask` and structured responses.
7. Add high-value tests, Docker, and README.
8. Review security, data claims, and architecture only after the happy path works.

## Guardrails
- Do not add RAG, embeddings, vector databases, arbitrary Python execution, or multi-agent runtime to the application.
- Do not introduce LangGraph unless the real runtime flow becomes stateful enough to justify a graph.
- Do not use the LLM as a calculator.
- Do not pass the full CSV to the model.
- Prefer one analytical tool over several overlapping tools; add another only when it has a distinct responsibility.
- Keep files cohesive. Do not imitate enterprise layering for a small challenge.
- Make business ambiguity visible. For example, “total sales” may mean quantity, revenue, or row count.
- For promotions, describe association and sample limitations; do not infer causality from a tiny observational subset.

## Phase completion report
After each phase, report: changed files, what now works, why the design was chosen, tests run, known limitation, and next smallest step.

## Interview learning
For each architectural change, be able to answer: what problem it solves, why a simpler alternative was rejected, how it fails, and how it would scale.
