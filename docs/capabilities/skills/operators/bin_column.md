# operator.bin_column

把数值列分成若干区间或给定边界，并写成一列分箱标签。

## When to use

把连续的热度/时长变成可做分组统计的类别。

Do not use it when:

- 按时间分阶段用 bin_time；要写算式列用 column_calc。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "bin_column", …}` in the analysis node’s `steps`, or set `operation` to `bin_column`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step keeps the upstream columns and appends the column(s) it names.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "bin_column",
    "steps": "[{\"op\": \"bin_column\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "bin_column",
    "steps": "[{\"op\": \"bin_column\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `bins` | array | `[]` |  |  |
| `labels` | array | `[]` |  |  |
| `new_col` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Every upstream column is still present, plus the column the step names.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/bin_column.md`
Skill page: `docs/capabilities/skills/operators/bin_column.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
