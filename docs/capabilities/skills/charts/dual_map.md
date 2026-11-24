# chart.dual_map

双层图：左右两层各自成簇，中间用流量连线表示跨层对应。

## When to use

把“施引/被引”或“方法/主题”两层结构放在一张图里。

Do not use it when:

- 只有一层结构时用知识图谱。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `map`, `source`, `target`, `weight`.

## Steps

1. Set the visualize node’s `chart_type` to `dual_map`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "dual_map"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "dual_map"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/dual_map.md`
Skill page: `docs/capabilities/skills/charts/dual_map.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
