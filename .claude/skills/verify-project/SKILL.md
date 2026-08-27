---
name: verify-project
description: Verify the repository before a commit, PR, or delivery. Use when asked to validate, test everything, check readiness, or invokes `/verify-project`.
---

# Verify project

Run the checks that exist in the repository and report truthfully what could and could not be verified.

Checklist:
- Python tests pass.
- Core known dataset results still match ground truth.
- API imports/starts and `/health` works.
- Unsafe SQL examples are rejected.
- No `.env`, API key, secret, cache, virtualenv, or generated junk is tracked.
- Docker builds and starts if Docker is available.
- README commands match the actual project.
- The implementation has no accidental RAG/arbitrary Python/multi-agent runtime creep.

Do not claim a Docker or real-provider test passed unless it was actually executed.
