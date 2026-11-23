# operator.forecast

用移动平均、Holt 或 Holt-Winters 对一条曲线外推若干期，并给出区间。

## When to use

情感演化曲线需要往后看几期（预测区间是模型给的，不是事实）。

Do not use it when:

- 期数不足 min_periods 时按名拒绝，不要用拟合线冒充观测。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: period).
- `value_col` names a column that must exist (default: sentiment_index).

## Steps

1. Put a step `{"op": "forecast", …}` in the analysis node’s `steps`, or set `operation` to `forecast`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `period`, `actual`, `predicted`, `lower`, `upper`, `horizon`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "forecast",
    "steps": "[{\"op\": \"forecast\", \"params\": {\"column\": \"period\", \"value_col\": \"sentiment_index\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "forecast",
    "steps": "[{\"op\": \"forecast\", \"params\": {\"column\": \"period\", \"value_col\": \"sentiment_index\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string | `period` |  |  |
| `value_col` | string | `sentiment_index` |  |  |
| `method` | string | `moving_average` |  | moving_average, holt, seasonal_naive, holt_winters |
| `horizon` | integer | `3` |  |  |
| `window` | integer | `3` |  |  |
| `alpha` | number | `0.5` |  |  |
| `beta` | number | `0.3` |  |  |
| `min_periods` | integer | `4` |  |  |
| `season` | integer | `7` |  |  |
| `gamma` | number | `0.35` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: period, actual, predicted, lower, upper, horizon.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/forecast.md`
Skill page: `docs/capabilities/skills/operators/forecast.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
