# chart.timezone

时区图：每个节点按年份序列铺开，颜色表示该年的出现量。

## When to use

看单个关键词在每一年是否出现、出现多少。

Do not use it when:

- 要按簇汇总用聚类时间线。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `年份序列`, `频次`.

## Steps

1. Set the visualize node’s `chart_type` to `timezone`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "timezone"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "timezone"
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
Documentation: `docs/capabilities/charts/timezone.md`
Skill page: `docs/capabilities/skills/charts/timezone.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
