---
name: next-phase
description: Advance the challenge by exactly one coherent implementation phase. Use when the user says to continue, start the next step, implement the next phase, or invokes `/next-phase`.
disable-model-invocation: false
---

# Next phase

1. Read `CLAUDE.md` and current repository state.
2. Identify the earliest incomplete high-priority phase.
3. Explain the goal in plain language before coding.
4. Implement only the smallest coherent slice needed for that phase.
5. Run the relevant deterministic tests or smoke checks.
6. Fix failures caused by the change.
7. Report changed files, what works, why it was designed that way, tests run, and the next phase.

Do not jump ahead into optional architecture while a required path is incomplete.
