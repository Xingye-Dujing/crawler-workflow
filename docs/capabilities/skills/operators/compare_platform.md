# operator.compare_platform

按平台列（或任意分组列）统计行数，并可对一列数值求均值/求和。

## When to use

多平台合并后要比较各平台的量与强度。

Do not use it when:

- 只想看单一平台时用 filter_rows + groupby_agg。

## Prerequisites

- An upstream table (the analysis node’s input).
- `platform_col` names a column that must exist (default: platform).

## Steps

1. Put a step `{"op": "compare_platform", …}` in the analysis node’s `steps`, or set `operation` to `compare_platform`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a fresh table whose column names come from the step’s own parameters.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "compare_platform",
    "steps": "[{\"op\": \"compare_platform\", \"params\": {\"platform_col\": \"platform\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "compare_platform",
    "steps": "[{\"op\": \"compare_platform\", \"params\": {\"platform_col\": \"platform\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `platform_col` | string | `platform` |  |  |
| `value_col` | string |  |  |  |
| `agg` | string | `mean` |  | mean, sum, median, min, max, count |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output column names equal the parameters the step was given.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/compare_platform.md`
Skill page: `docs/capabilities/skills/operators/compare_platform.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
