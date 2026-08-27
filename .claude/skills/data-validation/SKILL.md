---
name: data-validation
description: Validate analytical methodology, SQL results, dataset assumptions, and claims before presenting an answer or documenting findings.
---

# Data validation

Before accepting an analytical result:
1. State the metric definition and denominator.
2. Check date/filter scope.
3. Check nulls, duplicates, and sparse categorical values that may change interpretation.
4. Reproduce important claims with deterministic SQL.
5. Distinguish quantity from revenue and transaction/row count.
6. Separate observed association from causal claims.

Promotion analysis needs extra caution because promotional observations are sparse. Report sample size/concentration and avoid causal language unless the data/design supports it.

For money-like calculations, state the exact formula (for example `SUM(actual_quantity * actual_price)`) and do not invent a currency absent from the dataset.

Reference: Anthropic validate-data guidance at https://github.com/anthropics/knowledge-work-plugins/blob/main/data/skills/validate-data/SKILL.md
