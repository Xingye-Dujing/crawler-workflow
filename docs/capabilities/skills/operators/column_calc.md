# operator.column_calc

用一列或多列的算式派生新列（如 点赞 / 评论）。

## When to use

图表需要比率、差值或加权分，而表里只有原始计数时。

Do not use it when:

- 要按时间/数值分箱用 bin_column；要按行条件筛选用 filter_rows。

## Prerequisites

- An upstream table (the analysis node’s input).

## Steps

1. Put a step `{"op": "column_calc", …}` in the analysis node’s `steps`, or set `operation` to `column_calc`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step keeps the upstream columns and appends the column(s) it names.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "column_calc",
    "steps": "[{\"op\": \"column_calc\", \"params\": {\"new_col\": \"新列\", \"expr\": \"1\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "column_calc",
    "steps": "[{\"op\": \"column_calc\", \"params\": {\"new_col\": \"新列\", \"expr\": \"1\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `new_col` | string |  |  |  |
| `expr` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Every upstream column is still present, plus the column the step names.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/column_calc.md`
Skill page: `docs/capabilities/skills/operators/column_calc.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
