# chart.burst

突现词图：每个节点标出突现的起止年份与强度。

## When to use

找出某一时期突然升温的关键词。

Do not use it when:

- 看整体聚类年代跨度的聚簇时间线更合适。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `突现起始`, `突现结束`, `突现强度`.

## Steps

1. Set the visualize node’s `chart_type` to `burst`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "burst"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "burst"
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
Documentation: `docs/capabilities/charts/burst.md`
Skill page: `docs/capabilities/skills/charts/burst.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
