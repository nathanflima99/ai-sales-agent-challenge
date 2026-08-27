---
name: code-review
description: Review changes for correctness, simplicity, maintainability, testability, and challenge relevance. Use after meaningful code changes or before a commit/PR.
---

# Code review

Review the diff, not an imaginary enterprise system.

Rank findings by severity: blocking correctness/security, important reliability/maintainability, then optional polish.

Check especially:
- Is every new abstraction used now?
- Did the change keep the LLM/SQL responsibility split?
- Are calculations deterministic?
- Can generated SQL bypass the intended boundary?
- Are errors observable but sanitized?
- Do tests prove behavior rather than implementation?
- Can a reviewer understand the change quickly?
- Did a new dependency earn its complexity?

Do not demand stylistic rewrites when the current code is already clear. End with what is good enough to merge and what must change first.

Reference collection: https://github.com/swell-agents/coding-skills
