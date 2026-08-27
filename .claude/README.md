# Claude Code workspace

This repository keeps Claude-specific guidance under `.claude/` so the implementation remains reproducible and reviewable.

## Building blocks

- `CLAUDE.md`: permanent project facts, guardrails, and development rules.
- `.claude/skills/`: reusable procedures and domain guidance. Current Claude Code also exposes these as slash-invokable skills.
- `.claude/agents/`: project subagents with focused responsibilities.
- Hooks: intentionally omitted for now. Add only when a deterministic automatic check is worth the extra moving parts.

Current Claude Code documentation recommends Skills over legacy `.claude/commands/`; therefore this project does not duplicate workflows under `commands/`.

## Skills

- `ai-sales-agent-development`: primary project playbook.
- `fastapi`: API conventions for this challenge.
- `python-testing`: pytest conventions and mocking.
- `testing-strategy`: minimal high-value test selection.
- `dockerfile-best-practices`: pragmatic container guidance.
- `security-review`: secrets, API input, and SQL boundary review.
- `code-review`: focused engineering review.
- `data-validation`: analytical correctness and data-quality checks.
- `documentation`: README and architecture documentation.
- `skill-authoring`: how to add or improve project skills without bloating context.

## Subagents

- `architect`: challenge architecture and trade-offs.
- `implementer`: focused implementation of one phase at a time.
- `test-engineer`: deterministic tests and mocks.
- `data-analyst`: dataset semantics and analytical validation.
- `code-reviewer`: correctness, clarity, and overengineering review.
- `security-auditor`: SQL/tool/API/secrets boundary review.

## References

The project-specific skills are original, concise adaptations informed by public best-practice material from FastAPI, Anthropic, Microsoft, and community skill repositories. They are intentionally not verbatim copies, because upstream skills often include repository-specific rules that would be wrong here.

Useful upstream references:
- https://github.com/fastapi/fastapi/blob/master/fastapi/.agents/skills/fastapi/SKILL.md
- https://github.com/microsoft/agent-framework/blob/main/python/.github/skills/python-testing/SKILL.md
- https://github.com/anthropics/knowledge-work-plugins/blob/main/engineering/skills/testing-strategy/SKILL.md
- https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md
- https://github.com/cloudnative-co/claude-code-starter-kit/blob/main/skills/security-review/SKILL.md
- https://github.com/obeone/claude-skills
- https://github.com/swell-agents/coding-skills
