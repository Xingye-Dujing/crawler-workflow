# operator.bin_time

按给定时间边界把行切成阶段，并写入阶段名与可选的阶段序号。

## When to use

要做分阶段 LDA、主题演化或情感演化，先把时间轴切成“发酵/爆发/衰退”。

Do not use it when:

- 不知道边界时先用 suggest_stages 提议；只取日期用 extract_time。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "bin_time", …}` in the analysis node’s `steps`, or set `operation` to `bin_time`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step keeps the upstream columns and appends the column(s) it names.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "bin_time",
    "steps": "[{\"op\": \"bin_time\", \"params\": {\"column\": \"正文\", \"edges\": [\"2022-01-01\", \"2022-02-01\"], \"labels\": [\"发酵\"]}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "bin_time",
    "steps": "[{\"op\": \"bin_time\", \"params\": {\"column\": \"正文\", \"edges\": [\"2022-01-01\", \"2022-02-01\"], \"labels\": [\"发酵\"]}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `edges` | array | `[]` |  |  |
| `labels` | array | `[]` |  |  |
| `new_col` | string | `阶段` |  |  |
| `order_new_col` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Every upstream column is still present, plus the column the step names.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/bin_time.md`
Skill page: `docs/capabilities/skills/operators/bin_time.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
