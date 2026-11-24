# operator.sentiment_evolution

按时间列聚合情感标签，输出每期正/中/负占比、总量与可选的情感指数。

## When to use

要画情感演化曲线：时间 × 正负比例 × 强度。

Do not use it when:

- 要做预测用 forecast；要触发预警用 alert。

## Prerequisites

- An upstream table (the analysis node’s input).

## Steps

1. Put a step `{"op": "sentiment_evolution", …}` in the analysis node’s `steps`, or set `operation` to `sentiment_evolution`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "sentiment_evolution",
    "steps": "[{\"op\": \"sentiment_evolution\", \"params\": {}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "sentiment_evolution",
    "steps": "[{\"op\": \"sentiment_evolution\", \"params\": {}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `label_col` | string | `sentiment` |  |  |
| `positive` | string | `positive` |  |  |
| `neutral` | string | `neutral` |  |  |
| `negative` | string | `negative` |  |  |
| `new_col` | string | `sentiment_index` |  |  |
| `score_col` | string |  |  |  |
| `order_col` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/sentiment_evolution.md`
Skill page: `docs/capabilities/skills/operators/sentiment_evolution.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
