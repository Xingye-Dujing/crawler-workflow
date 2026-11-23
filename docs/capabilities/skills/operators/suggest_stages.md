# operator.suggest_stages

按时间列的每日/每窗行数曲线，提议若干个阶段边界（起点、终点、峰值）。

## When to use

不知道该把事件切成几段时，先让数据给出候选边界，再人工确认。

Do not use it when:

- 已有明确边界时直接 bin_time，不要用建议值覆盖已知事实。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "suggest_stages", …}` in the analysis node’s `steps`, or set `operation` to `suggest_stages`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `序号`, `起点`, `终点`, `天数`, `行数`, `峰值日`, `峰值计数`, `依据`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "suggest_stages",
    "steps": "[{\"op\": \"suggest_stages\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "suggest_stages",
    "steps": "[{\"op\": \"suggest_stages\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `min_days` | integer | `3` |  |  |
| `max_windows` | integer | `6` |  |  |
| `peak_ratio` | number | `2.0` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: 序号, 起点, 终点, 天数, 行数, 峰值日, 峰值计数, 依据.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/suggest_stages.md`
Skill page: `docs/capabilities/skills/operators/suggest_stages.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
