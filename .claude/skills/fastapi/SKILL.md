---
name: fastapi
description: FastAPI and Pydantic guidance adapted for this challenge. Use when creating or reviewing API routes, request/response models, dependencies, errors, or health endpoints.
---

# FastAPI for this project

Keep the HTTP layer thin. Routes validate input, call application services, translate known failures to HTTP responses, and return typed Pydantic models.

## Conventions
- Use `FastAPI()` with explicit metadata only where useful.
- Use Pydantic models for `/ask` request and response bodies.
- Reject blank questions at validation time.
- Keep `/health` independent from the LLM when possible.
- Do not return raw exceptions or stack traces to clients.
- Prefer explicit dependency injection only when it improves testability; avoid dependency graphs for trivial objects.
- Let FastAPI generate OpenAPI/Swagger instead of writing separate API docs.
- Keep model/provider credentials in environment-backed configuration.

## Review checklist
Check status codes, response schema stability, validation errors, async/sync boundaries, exception handling, and whether route code contains business or SQL logic that belongs elsewhere.

Reference: official FastAPI agent skill at https://github.com/fastapi/fastapi/blob/master/fastapi/.agents/skills/fastapi/SKILL.md
