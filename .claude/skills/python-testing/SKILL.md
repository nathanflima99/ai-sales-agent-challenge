---
name: python-testing
description: Pytest guidance for this project. Use when writing, changing, running, or debugging Python tests and test fixtures.
---

# Python testing

Use pytest and optimize for confidence per test, not raw test count.

## Rules
- Unit-test deterministic code directly.
- Mock LLM/network calls in the normal suite.
- Mark any real-provider test as optional/integration and make it skippable without an API key.
- Prefer small fixtures with descriptive names.
- Test public behavior rather than private implementation details.
- Never weaken an assertion merely to make a refactor pass.

## Ground truth
When the supplied dataset is present, retain deterministic assertions for:
- `Product_1359` -> `95,112,506` actual quantity.
- `Whse_J` -> `617,421,620` actual quantity.
- total actual quantity -> `953,555,461`.
- total planned quantity -> `949,259,991`.
- actual minus planned -> `4,295,470`.

Reference: Microsoft Agent Framework Python testing guidance at https://github.com/microsoft/agent-framework/blob/main/python/.github/skills/python-testing/SKILL.md
