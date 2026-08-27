---
name: dockerfile-best-practices
description: Pragmatic Docker guidance for this Python/FastAPI challenge. Use when creating, optimizing, debugging, or reviewing Dockerfile and container runtime behavior.
---

# Dockerfile best practices

The evaluator should be able to clone, build, and run the API with very few commands.

## Priorities
- Use a small supported Python base image.
- Copy dependency metadata before application files so dependency layers can cache.
- Install only runtime dependencies in the final image.
- Use `--no-cache-dir` for pip where appropriate.
- Set a clear `WORKDIR`.
- Do not bake `.env`, API keys, virtualenvs, caches, or Git metadata into the image.
- Run Uvicorn bound to `0.0.0.0`.
- Prefer a non-root runtime user once the basic image works and file permissions are clear.
- Do not add multi-stage builds unless they materially reduce build/runtime complexity.

Always verify with an actual `docker build` and a health request after `docker run`.

Reference: https://github.com/obeone/claude-skills
