---
name: testing-strategy
description: Design the smallest high-value test plan for a feature or phase. Use when deciding what to test, whether an integration test is needed, or how to avoid low-value coverage work.
---

# Testing strategy

Prioritize business-critical behavior, data integrity, error paths, and security boundaries.

For this challenge, the core suite should prove:
1. Dataset/schema is usable or fails clearly.
2. DuckDB analytical results match known ground truth.
3. SQL boundary allows normal read queries and blocks unsafe/multiple statements.
4. `/health` works.
5. `/ask` validation works and the agent path can be tested with a mocked model/tool call.
6. Failures do not leak secrets or stack traces.

Skip trivial getters, framework internals, and large end-to-end matrices. One optional real-LLM smoke test is enough after deterministic tests are stable.

Reference: Anthropic testing strategy skill at https://github.com/anthropics/knowledge-work-plugins/blob/main/engineering/skills/testing-strategy/SKILL.md
