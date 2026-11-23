# operator.alert

按连续涨跌、摆动幅度、升温与量能规则，在曲线上标出二次爆发预警点。

## When to use

要在情感/热度曲线上自动指出“需要人工复核的时刻”。

Do not use it when:

- 预警是规则给出的候选，不是因果结论；要看趋势用 forecast。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: period).
- `index_col` names a column that must exist (default: sentiment_index).

## Steps

1. Put a step `{"op": "alert", …}` in the analysis node’s `steps`, or set `operation` to `alert`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `period`, `signal`, `value`, `threshold`, `reason`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "alert",
    "steps": "[{\"op\": \"alert\", \"params\": {\"column\": \"period\", \"index_col\": \"sentiment_index\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "alert",
    "steps": "[{\"op\": \"alert\", \"params\": {\"column\": \"period\", \"index_col\": \"sentiment_index\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string | `period` |  |  |
| `index_col` | string | `sentiment_index` |  |  |
| `intensity_col` | string |  |  |  |
| `volume_col` | string |  |  |  |
| `streak` | integer | `2` |  |  |
| `swing` | number | `0.2` |  |  |
| `heating` | number | `0.15` |  |  |
| `volume_floor` | number | `0.6` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: period, signal, value, threshold, reason.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/alert.md`
Skill page: `docs/capabilities/skills/operators/alert.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
