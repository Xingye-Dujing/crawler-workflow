# operator.extract_time

从时间列派生日期、小时、星期、月或年，写成新列。

## When to use

事件研究要按天聚合、看周内节律，或给分阶段准备时间基准列。

Do not use it when:

- 要按边界切成阶段用 bin_time；只改类型用 convert_type。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "extract_time", …}` in the analysis node’s `steps`, or set `operation` to `extract_time`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step keeps the upstream columns and appends the column(s) it names.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "extract_time",
    "steps": "[{\"op\": \"extract_time\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "extract_time",
    "steps": "[{\"op\": \"extract_time\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `new_col` | string | `日期` |  |  |
| `part` | string | `date` |  | date, hour, weekday, month, year |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Every upstream column is still present, plus the column the step names.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/extract_time.md`
Skill page: `docs/capabilities/skills/operators/extract_time.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
