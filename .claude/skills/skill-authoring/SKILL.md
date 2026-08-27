---
name: skill-authoring
description: Create or improve project Claude skills. Use when adding a repeated workflow, splitting large guidance, tuning skill triggers, or reviewing `.claude/skills`.
---

# Skill authoring

Create a skill only for guidance that will be reused or should load on demand.

## Method
1. Define the exact trigger/use case.
2. Write a short `description` that says what it does and when to use it.
3. Keep the body imperative and task-focused.
4. Keep permanent project facts in `CLAUDE.md`, not duplicated in every skill.
5. Put large optional reference material in sibling `references/` files instead of bloating the main skill.
6. Avoid hidden side effects or broad tool permissions.
7. Test the skill on a few prompts that should trigger it and a few that should not.

Prefer a small set of strong skills over dozens of overlapping ones.

Reference: Anthropic skill creator at https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md
